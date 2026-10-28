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
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter
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

from . import theme as theming

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


class TranslationPopup(QWidget):
    def __init__(
        self, width: int = 460, max_height: int = 420, theme: str = "light"
    ) -> None:
        super().__init__()
        self._max_height = max_height
        self._theme = theming.get(theme)
        self._pending = False

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
        body.addWidget(self._source)
        body.addSpacing(8)
        body.addWidget(self._scroll)

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

    # -- appearance ---------------------------------------------------------

    def _apply_width(self, width: int) -> None:
        card = width - theming.SHADOW_MARGIN * 2
        self._content_width = card - theming.CARD_PADDING * 2 - _SCROLLBAR_GUTTER
        self.setFixedWidth(width)
        self._source.setFixedWidth(self._content_width)
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
        self._pending = True
        self._heading.setText("TRANSLATING…")
        self._source.setText(_preview(source_text))
        self._set_translation("…", state="pending")
        self._copy_button.setEnabled(False)
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
        self._pending = False
        self._heading.setText(heading)
        self._source.setText(_preview(source_text))
        self._set_translation(translated, state="ok")
        self._copy_button.setEnabled(True)
        self._present()

    def show_error(self, message: str) -> None:
        self._pending = False
        self._heading.setText("TRANSLATION FAILED")
        self._source.setText("")
        self._set_translation(message, state="error")
        self._copy_button.setEnabled(False)
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
        chrome = self.sizeHint().height() - 1

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
        super().hideEvent(event)


def _language_label(code: str) -> str:
    if not code:
        return "?"
    return _LANGUAGE_LABELS.get(code.lower(), code.upper())


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
