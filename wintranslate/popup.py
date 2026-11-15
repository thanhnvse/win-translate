"""The floating result window.

It behaves like a tooltip rather than a window: no taskbar entry, no title bar,
always on top, gone as soon as it loses focus. The user asked for a
translation, not for something else to manage.

Shape follows the macOS alert it was drawn from -- a frosted pane with a large
radius, a soft wide shadow instead of a hard border, the translation as the one
bold line, and two equal buttons at the foot.

The height logic here broke three times while it was first written: layouts
cache their size hints, a fixed height clamps the measurement taken for the
next translation, and the scroll area's viewport paints white unless told not
to. Each of those has a test; none of it is incidental.

The speaker buttons sit beside the text they read rather than in the
Close/Copy row: at the narrowest width Settings allows (280 px) that row has no
room for two more buttons, and beside the text there is no doubt which one a
button reads.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import languages
from . import theme as theming
from .speech import Speaker

log = logging.getLogger(__name__)

#: Gap between the pointer and the card, so the pointer never covers the text.
_CURSOR_OFFSET = QPoint(14, 18)

#: Keep this far from the screen edge when clamping.
_SCREEN_MARGIN = 8

#: Reserved so a long translation's scrollbar never overlaps the text.
_SCROLLBAR_GUTTER = 12

#: Even one word gets this much room, so the card never collapses to a sliver.
_MIN_TEXT_HEIGHT = 22

#: Roughly three lines, held open while the translation is in flight.
_PENDING_TEXT_HEIGHT = 46

#: Qt's own "no maximum", used to lift a previously fixed height.
_QWIDGETSIZE_MAX = 16777215

_LANGUAGE_LABELS = {"vi": "VIETNAMESE", "en": "ENGLISH"}

#: The speaker buttons: a square this big, this far from the text it reads.
_SPEAK_SIZE = 20
_SPEAK_GAP = 6
_SPEAK_ICON = 16
#: Width the text gives up so the button fits beside it.
_SPEAK_SLOT = _SPEAK_SIZE + _SPEAK_GAP

#: Where a user adds a voice, for the tooltip of a language that has none.
#: Voices are listed once per run, so a new one is seen after a restart.
if sys.platform == "darwin":
    _ADD_VOICE_HINT = (
        "Add one in System Settings > Accessibility > Spoken Content > "
        "System voice > Manage Voices, then restart win-translate."
    )
elif sys.platform == "win32":
    _ADD_VOICE_HINT = (
        "Add one in Settings > Time & language > Speech > Manage voices, "
        "then restart win-translate."
    )
else:
    _ADD_VOICE_HINT = "Install one for your speech engine, then restart win-translate."

#: How long a reading may take to start before the button stops showing it.
#: Qt's engines can fail without a word (see speech.py), which would leave
#: "Stop" on for good. Generous because winrt synthesises the whole text
#: before it plays a sound.
_SPEECH_START_TIMEOUT_MS = 5000

SOURCE = "source"
TRANSLATION = "translation"


class TranslationPopup(QWidget):
    def __init__(
        self,
        width: int = 460,
        max_height: int = 420,
        theme: str = "light",
        speaker: Speaker | None = None,
    ) -> None:
        super().__init__()
        self._max_height = max_height
        self._theme = theming.get(theme)
        self._pending = False
        #: "pending", "result" or "error": what the card is showing.
        self._mode = "pending"

        # What the speaker buttons read. The source label shows a 120-character
        # preview, so the full selection is kept here.
        self._source_text = ""
        self._source_code: str | None = None
        self._target_code: str | None = None
        self._speaker = speaker if speaker is not None else Speaker(self)
        # The button the user last asked to read, and the one the engine is
        # reading now. They differ for a moment after a click, because an
        # engine may report the stop of the old text after the click that
        # started the new one.
        self._speech_wanted: str | None = None
        self._speech_active: str | None = None
        self._speaker.speaking.connect(self._on_speaking)
        self._speaker.stopped.connect(self._on_speech_stopped)
        self._speech_watchdog = QTimer(self)
        self._speech_watchdog.setSingleShot(True)
        self._speech_watchdog.setInterval(_SPEECH_START_TIMEOUT_MS)
        self._speech_watchdog.timeout.connect(self._on_speech_not_started)

        # No system shadow: paintEvent draws the card's own, in the transparent
        # margin around it. The system one is traced from everything that is
        # not fully transparent, that hand-drawn shadow included, so it outlines
        # the whole margin in a dark ring -- the macOS window shadow did, on
        # every theme.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(width)

        outer = QVBoxLayout(self)
        # The shadow is drawn outside the card, so the layout has to leave it room.
        margin = theming.SHADOW_MARGIN
        outer.setContentsMargins(margin, margin - 6, margin, margin)

        self._card = QFrame(objectName="card")
        outer.addWidget(self._card)

        body = QVBoxLayout(self._card)
        pad = theming.CARD_PADDING
        body.setContentsMargins(pad, pad - 6, pad, pad - 6)
        body.setSpacing(0)

        self._heading = QLabel(objectName="heading")
        body.addWidget(self._heading)
        body.addSpacing(10)

        # PlainText, not the default AutoText: a selection such as "<b>x</b>"
        # must be shown as written, not rendered as markup.
        self._translation = QLabel(
            objectName="translation", wordWrap=True, textFormat=Qt.PlainText
        )
        # Interaction is set per theme in _apply_theme: a gradient colour and
        # selectable text cannot coexist. See the note there.
        self._translation.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self._scroll = QScrollArea()
        # Deliberately not widgetResizable: the label owns a fixed width so that
        # heightForWidth() has something definite to answer, which is what the
        # card's height is derived from.
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidget(self._translation)
        self._scroll.viewport().setAutoFillBackground(False)
        self._translation.setAutoFillBackground(False)

        # Source first, then the translation under it: the eye starts at what
        # was selected and moves down to what came back.
        self._source = QLabel(
            objectName="source", wordWrap=True, textFormat=Qt.PlainText
        )
        self._speak_buttons = {
            SOURCE: self._make_speak_button(SOURCE, "Read the original aloud"),
            TRANSLATION: self._make_speak_button(
                TRANSLATION, "Read the translation aloud"
            ),
        }
        body.addLayout(self._speak_row(self._source, self._speak_buttons[SOURCE]))
        body.addSpacing(8)
        self._translation_row = self._speak_row(
            self._scroll, self._speak_buttons[TRANSLATION]
        )
        body.addLayout(self._translation_row)

        body.addSpacing(14)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self._close_button = QPushButton("Close", objectName="secondary")
        self._close_button.clicked.connect(self.hide)
        self._copy_button = QPushButton("Copy", objectName="primary")
        self._copy_button.clicked.connect(self._copy_translation)
        buttons.addWidget(self._close_button, 1)
        buttons.addWidget(self._copy_button, 1)
        body.addLayout(buttons)

        self._apply_width(width)
        self._apply_theme()

    def _make_speak_button(self, role: str, name: str) -> QPushButton:
        button = QPushButton(objectName="speak")
        button.setFixedSize(_SPEAK_SIZE, _SPEAK_SIZE)
        button.setIconSize(QSize(_SPEAK_ICON, _SPEAK_ICON))
        # Never takes keyboard focus: which child holds focus decides how the
        # popup notices it was clicked away from (see changeEvent).
        button.setFocusPolicy(Qt.NoFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(name)
        button.setEnabled(False)
        button.clicked.connect(lambda: self._toggle_speech(role))
        return button

    @staticmethod
    def _speak_row(content: QWidget, button: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(_SPEAK_GAP)
        row.addWidget(content, 1)
        row.addWidget(button, 0, Qt.AlignTop)
        return row

    # -- appearance ---------------------------------------------------------

    def _apply_width(self, width: int) -> None:
        card = width - theming.SHADOW_MARGIN * 2
        text = card - theming.CARD_PADDING * 2 - _SPEAK_SLOT
        self._content_width = text - _SCROLLBAR_GUTTER
        self.setFixedWidth(width)
        # The source has no scrollbar, so it also takes the gutter; both
        # buttons then line up at the card's right edge.
        self._source.setFixedWidth(text)
        self._translation.setFixedWidth(self._content_width)

    def _apply_theme(self) -> None:
        self.setStyleSheet(theming.popup_stylesheet(self._theme))
        # Selectable text and gradient text are mutually exclusive in QLabel.
        # TextSelectableByMouse switches rendering to a QTextDocument, whose
        # character format takes a solid colour, so the gradient is dropped and
        # the text falls back to black -- measured, not inferred. The themes
        # that ask for a gradient give up selection for it; Copy still takes
        # the whole translation, so only picking out part of it is lost.
        self._translation.setTextInteractionFlags(
            Qt.NoTextInteraction
            if self._theme.text_stops
            else Qt.TextSelectableByMouse
        )
        self._speak_icon = _speaker_icon(self._theme.dim)
        self._stop_icon = _stop_icon(self._theme.accent)
        self._refresh_speak_buttons()
        self.update()

    def paintEvent(self, event) -> None:
        """Draw the card's shadow by hand.

        QGraphicsDropShadowEffect renders the widget and everything under it
        into a pixmap first, which softens every glyph: measured on this
        popup, the largest edge step across a line of text fell from 255 to 79.
        Stacked translucent rounded rectangles cost nothing and leave the text
        drawn by the normal path.
        """
        card = QRectF(self._card.geometry())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        layers = 12
        for step in range(layers, 0, -1):
            spread = step * 1.7
            colour = QColor(self._theme.shadow)
            colour.setAlpha(max(2, self._theme.shadow_alpha // (layers * 2)))
            painter.setBrush(colour)
            painter.drawRoundedRect(
                card.adjusted(-spread, -spread + 5, spread, spread + 7),
                theming.RADIUS + spread * 0.4,
                theming.RADIUS + spread * 0.4,
            )
        super().paintEvent(event)

    def apply_appearance(self, width: int, max_height: int, theme: str) -> None:
        """Re-dress the popup in place, for a settings change.

        Rebuilding it instead would drop whatever is on screen and break the
        signal connections the app holds to this object.
        """
        self._max_height = max_height
        self._theme = theming.get(theme)
        self._apply_width(width)
        self._apply_theme()
        # Property selectors are re-read only on a re-polish, so a state set
        # under the old stylesheet would keep the old colour.
        for widget in (self, self._card, self._translation):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        if self.isVisible():
            self._fit_height()

    # -- states -------------------------------------------------------------

    def show_pending(self, source_text: str) -> None:
        self.stop_speech()
        self._pending = True
        self._mode = "pending"
        self._source_text = source_text
        self._source_code = None
        self._target_code = None
        self._heading.setText("TRANSLATING…")
        self._source.setText(_preview(source_text))
        self._set_translation("…", state="pending")
        self._copy_button.setEnabled(False)
        self._refresh_speak_buttons()
        self._present()

    def show_result(
        self,
        source_text: str,
        translated: str,
        detected_source: str | None,
        target: str = "vi",
        show_detected: bool = True,
    ) -> None:
        heading = _language_label(target)
        if show_detected and detected_source:
            heading = f"{_language_label(detected_source)} → {heading}"
        self.stop_speech()
        self._pending = False
        self._mode = "result"
        self._source_text = source_text
        self._source_code = detected_source
        self._target_code = target
        self._heading.setText(heading)
        self._source.setText(_preview(source_text))
        self._set_translation(translated, state="ok")
        self._copy_button.setEnabled(True)
        self._refresh_speak_buttons()
        self._present()

    def show_error(self, message: str) -> None:
        self.stop_speech()
        self._pending = False
        self._mode = "error"
        self._source_text = ""
        self._source_code = None
        self._target_code = None
        self._heading.setText("TRANSLATION FAILED")
        self._source.setText("")
        self._set_translation(message, state="error")
        self._copy_button.setEnabled(False)
        self._refresh_speak_buttons()
        self._present()

    def _set_translation(self, text: str, state: str) -> None:
        self._translation.setText(text)
        self._translation.setProperty("state", state)
        self._translation.style().unpolish(self._translation)
        self._translation.style().polish(self._translation)

    # -- geometry -----------------------------------------------------------

    def _present(self) -> None:
        self._fit_height()
        if not self.isVisible():
            self.move(_position_near_cursor(self.width(), self.height()))
        self.show()
        self.raise_()
        self.activateWindow()

    def _fit_height(self) -> None:
        """Grow with the content up to the ceiling, then scroll.

        The chrome around the text is measured rather than assumed, because the
        source preview wraps to one or two lines depending on the selection.
        """
        # Release the height pinned by the previous translation. While a fixed
        # height is in force it clamps that widget's own measurements, so
        # heightForWidth would keep reporting the old text's height.
        for widget in (self, self._translation):
            widget.setMinimumHeight(0)
            widget.setMaximumHeight(_QWIDGETSIZE_MAX)

        text_height = self._translation.heightForWidth(self._content_width)
        if text_height <= 0:
            text_height = self._translation.sizeHint().height()
        if self._pending:
            # While waiting there is only an ellipsis to measure. Opening at
            # that size and jumping once the answer lands reads as a glitch, so
            # the card reserves roughly what an answer takes.
            text_height = max(text_height, _PENDING_TEXT_HEIGHT)
        self._translation.setFixedHeight(text_height)

        self._scroll.setFixedHeight(1)
        self._relayout()
        # Everything but the translation's row. Not "minus the 1 px scroll
        # area": the speaker button beside it holds the row at its own height.
        chrome = self.sizeHint().height() - self._translation_row.sizeHint().height()

        budget = max(_MIN_TEXT_HEIGHT, self._max_height - chrome)
        # Decide the scrollbar from the numbers: "as needed" shows a bar for a
        # sub-pixel overflow on text that visibly fits.
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if text_height > budget else Qt.ScrollBarAlwaysOff
        )
        self._scroll.setFixedHeight(min(text_height, budget))
        self._relayout()
        self.setFixedHeight(self.sizeHint().height())

    def _relayout(self) -> None:
        """Force both layouts to recompute.

        activate() alone is not enough: Qt caches each layout's size hint and
        only invalidate() marks it dirty, so without this the popup keeps
        reporting the height it had for the previous translation.
        """
        for layout in (self._card.layout(), self.layout()):
            layout.invalidate()
            layout.activate()

    # -- reading aloud -------------------------------------------------------

    def _speech_target(self, role: str) -> tuple[str, str | None]:
        """The text a button reads and the language code to read it in."""
        if role == SOURCE:
            return self._source_text, self._source_code
        return self._translation.text(), self._target_code

    def _refresh_speak_buttons(self) -> None:
        for role, button in self._speak_buttons.items():
            if self._mode == "error":
                # Nothing to read: the source is blank and the text is an error.
                button.hide()
                continue
            button.show()
            speaking = self._speech_active == role
            button.setIcon(self._stop_icon if speaking else self._speak_icon)
            enabled, tip = self._speak_state(role)
            button.setEnabled(enabled)
            button.setToolTip("Stop reading" if speaking else tip)

    def _speak_state(self, role: str) -> tuple[bool, str]:
        """Whether a button can read, and the tooltip that says why or why not.

        Never reads one language with another language's voice: a language
        with no voice of its own gets a disabled button instead.
        """
        what = "the original" if role == SOURCE else "the translation"
        if self._mode != "result":
            return False, f"Read {what} aloud"
        text, code = self._speech_target(role)
        if not code:
            return False, "The language of the original was not detected."
        if not text.strip():
            return False, f"Read {what} aloud"
        if not self._speaker.is_available():
            return False, "Text to speech is not available on this system."
        name = _language_name(code)
        voice = self._speaker.voice_for(code)
        if voice is None:
            return False, f"No {name} voice is installed. {_ADD_VOICE_HINT}"
        by = f", voice {voice.name}" if voice.name else ""
        return True, f"Read {what} aloud ({name}{by})"

    def _toggle_speech(self, role: str) -> None:
        """Read ``role``'s text, or stop if that is what is being read."""
        if self._speech_active == role:
            self.stop_speech()
            return
        text, code = self._speech_target(role)
        self._speech_wanted = role
        if self._speaker.say(text, code):
            # Shown at once rather than when the engine reports it, which on
            # macOS comes a few milliseconds later.
            self._speech_active = role
            self._speech_watchdog.start()
        else:
            self._speech_wanted = None
        self._refresh_speak_buttons()

    def prepare_speech(self) -> None:
        """Start the speech engine ahead of the first translation."""
        self._speaker.prepare()

    def stop_speech(self) -> None:
        self._speech_watchdog.stop()
        self._speech_wanted = None
        self._speech_active = None
        self._speaker.stop()
        self._refresh_speak_buttons()

    def _on_speaking(self) -> None:
        # Whatever the engine started is what was last asked for; after a stop
        # nothing was, so a late start report changes nothing.
        self._speech_watchdog.stop()
        self._speech_active = self._speech_wanted
        self._refresh_speak_buttons()

    def _on_speech_not_started(self) -> None:
        """The engine never said it started. Show the button idle again,
        unless the engine is in fact reading.

        sapi can start a new text without reporting it (see speech.py), so the
        engine's own state is asked first. Otherwise the engine is left alone:
        on winrt a long text may still be synthesising, and if it does start,
        _on_speaking puts "Stop" back, because what was asked for is still
        remembered.
        """
        if self._speech_active is None:
            return
        if self._speaker.is_speaking():
            return
        log.warning(
            "Reading aloud did not start within %d ms%s",
            _SPEECH_START_TIMEOUT_MS,
            f": {self._speaker.last_error()}" if self._speaker.last_error() else "",
        )
        self._speech_active = None
        self._refresh_speak_buttons()

    def _on_speech_stopped(self) -> None:
        self._speech_active = None
        self._refresh_speak_buttons()

    # -- behaviour ----------------------------------------------------------

    def _copy_translation(self) -> None:
        QApplication.clipboard().setText(self._translation.text())
        self._copy_button.setText("Copied")
        QTimer.singleShot(1500, lambda: self._copy_button.setText("Copy"))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self.hide()
        super().focusOutEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        # focusOutEvent alone misses a click into another app: keyboard focus
        # sits on a child (the scroll area), so the popup itself never loses
        # it. On macOS the window server also hides a tool window when the app
        # deactivates without telling Qt, and the next popup would then reopen
        # at the old spot instead of by the pointer.
        # Not isActiveWindow(): under the macOS style a parentless tool window
        # counts as active whenever it is shown (SH_Widget_ShareActivation).
        if (
            event.type() == QEvent.ActivationChange
            and self.isVisible()
            and QApplication.activeWindow() is not self
        ):
            self.hide()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._copy_button.setText("Copy")
        self.stop_speech()
        super().hideEvent(event)


def _language_label(code: str) -> str:
    if not code:
        return "?"
    return _LANGUAGE_LABELS.get(code.lower(), code.upper())


def _language_name(code: str) -> str:
    language = languages.get(code)
    return language.name if language is not None else code.upper()


def _paint_icon(draw, colour: str, faded: bool = False) -> QIcon:
    """An icon drawn in code at 1x, 2x and 3x.

    Drawn rather than loaded from an SVG so it takes each theme's colour, and
    so it cannot go missing with the SVG icon-engine plugin in a frozen build.
    With ``faded``, a see-through copy serves the disabled state.
    """
    icon = QIcon()
    modes = [(QIcon.Normal, 1.0)] + ([(QIcon.Disabled, 0.35)] if faded else [])
    for mode, alpha in modes:
        paint = QColor(colour)
        paint.setAlphaF(alpha)
        for scale in (1, 2, 3):
            pixmap = QPixmap(_SPEAK_ICON * scale, _SPEAK_ICON * scale)
            pixmap.setDevicePixelRatio(scale)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            draw(painter, paint)
            painter.end()
            icon.addPixmap(pixmap, mode)
    return icon


def _draw_speaker(painter: QPainter, colour: QColor) -> None:
    """A speaker with two sound waves, on a 16-unit square."""
    body = QPainterPath()
    body.moveTo(2.0, 6.0)
    body.lineTo(4.8, 6.0)
    body.lineTo(8.6, 2.8)
    body.lineTo(8.6, 13.2)
    body.lineTo(4.8, 10.0)
    body.lineTo(2.0, 10.0)
    body.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawPath(body)
    pen = QPen(colour, 1.4)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    centre = QPointF(8.6, 8.0)
    for radius in (3.0, 5.6):
        box = QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2)
        painter.drawArc(box, -50 * 16, 100 * 16)


def _draw_stop(painter: QPainter, colour: QColor) -> None:
    """A rounded square: what a click does while the text is being read."""
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawRoundedRect(QRectF(3.5, 3.5, 9.0, 9.0), 2.0, 2.0)


def _speaker_icon(colour: str) -> QIcon:
    return _paint_icon(_draw_speaker, colour, faded=True)


def _stop_icon(colour: str) -> QIcon:
    return _paint_icon(_draw_stop, colour)


def _preview(text: str, limit: int = 120) -> str:
    """One-line, length-capped echo of the source, so the user can confirm what
    was actually captured when the selection was not what they expected."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


def _position_near_cursor(width: int, height: int) -> QPoint:
    """Place the popup by the pointer, flipping and clamping to stay on screen."""
    cursor = QCursor.pos()
    screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
    area = screen.availableGeometry()

    x = cursor.x() + _CURSOR_OFFSET.x()
    y = cursor.y() + _CURSOR_OFFSET.y()

    # Flip to the other side of the pointer rather than sliding, so the card
    # never lands under the cursor.
    if x + width > area.right() - _SCREEN_MARGIN:
        x = cursor.x() - width - _CURSOR_OFFSET.x()
    if y + height > area.bottom() - _SCREEN_MARGIN:
        y = cursor.y() - height - _CURSOR_OFFSET.y()

    x = max(area.left() + _SCREEN_MARGIN, min(x, area.right() - width - _SCREEN_MARGIN))
    y = max(area.top() + _SCREEN_MARGIN, min(y, area.bottom() - height - _SCREEN_MARGIN))
    return QPoint(x, y)
