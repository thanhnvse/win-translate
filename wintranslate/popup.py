"""The floating result window.

It deliberately behaves like a tooltip rather than a normal window: no taskbar
entry, no title bar, always on top, and it closes as soon as it loses focus.
The user asked for a translation, not for another window to manage.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
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

#: Gap between the mouse pointer and the popup's corner, so the pointer never
#: covers the first line of text.
_CURSOR_OFFSET = QPoint(14, 18)

#: Keep the popup this far from the screen edge when clamping.
_SCREEN_MARGIN = 8

#: Left/right padding inside the card.
_CARD_PADDING = 14

#: Reserved so a long translation's scrollbar never overlaps the text.
_SCROLLBAR_GUTTER = 12

#: Even a one-word translation gets this much room, so the popup never collapses
#: to a sliver while the layout is settling.
_MIN_TEXT_HEIGHT = 22

#: Qt's own "no maximum" sentinel, used to lift a previously fixed height.
_QWIDGETSIZE_MAX = 16777215

#: Footer hint. Shown whenever the popup is not briefly confirming a copy.
_HINT_TEXT = "Esc to close"

_STYLESHEET = """
#card {
    background-color: #1e1f24;
    border: 1px solid #34363d;
    border-radius: 10px;
}
#heading {
    color: #8b8d96;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
}
#source {
    color: #7e808a;
    font-size: 12px;
}
#translation {
    color: #f2f3f5;
    font-size: 14px;
}
#translation[state="error"] {
    color: #ff8a80;
}
#translation[state="pending"] {
    color: #8b8d96;
    font-style: italic;
}
#hint {
    color: #62646d;
    font-size: 10px;
}
QPushButton {
    background-color: #2b2d34;
    color: #d8dae0;
    border: 1px solid #3a3d45;
    border-radius: 5px;
    padding: 3px 10px;
    font-size: 11px;
}
QPushButton:hover { background-color: #343740; }
QPushButton:pressed { background-color: #26282e; }
#close {
    background: transparent;
    border: none;
    color: #8b8d96;
    font-size: 15px;
    padding: 0 4px;
}
#close:hover { color: #f2f3f5; }
/* The scroll area's *viewport* is a separate widget with its own palette, and
   it defaults to QPalette.Base -- white. Without these three selectors the
   translation is near-white text drawn on a white block. */
QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #43454d; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class TranslationPopup(QWidget):
    def __init__(self, width: int = 460, max_height: int = 420) -> None:
        super().__init__()
        self._max_height = max_height
        # Width available to wrapped text: the popup minus the card's left and
        # right padding, minus a gutter for the scrollbar. Both labels are pinned
        # to it so `heightForWidth` has a width to answer for.
        self._content_width = width - _CARD_PADDING * 2 - _SCROLLBAR_GUTTER

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(width)
        self.setStyleSheet(_STYLESHEET)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(objectName="card")
        outer.addWidget(card)
        self._card = card

        layout = QVBoxLayout(card)
        layout.setContentsMargins(_CARD_PADDING, 12, _CARD_PADDING, 10)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading_row.setSpacing(6)
        self._heading = QLabel(objectName="heading")
        heading_row.addWidget(self._heading)
        heading_row.addStretch(1)
        close_button = QPushButton("✕", objectName="close")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setFixedSize(20, 18)
        close_button.clicked.connect(self.hide)
        heading_row.addWidget(close_button)
        layout.addLayout(heading_row)

        self._source = QLabel(objectName="source", wordWrap=True)
        self._source.setFixedWidth(self._content_width)
        layout.addWidget(self._source)

        self._translation = QLabel(objectName="translation", wordWrap=True)
        self._translation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._translation.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._translation.setFixedWidth(self._content_width)

        scroll = QScrollArea()
        # Deliberately NOT widgetResizable: the label owns a fixed width so that
        # heightForWidth() has something definite to answer, which is what the
        # popup's own height is derived from.
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._translation)
        scroll.viewport().setAutoFillBackground(False)
        self._translation.setAutoFillBackground(False)
        self._scroll = scroll
        layout.addWidget(scroll)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self._hint = QLabel(_HINT_TEXT, objectName="hint")
        footer.addWidget(self._hint)
        footer.addStretch(1)
        self._copy_button = QPushButton("Copy")
        self._copy_button.clicked.connect(self._copy_translation)
        footer.addWidget(self._copy_button)
        layout.addLayout(footer)

    def show_pending(self, source_text: str) -> None:
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
        self._heading.setText(heading)
        self._source.setText(_preview(source_text))
        self._set_translation(translated, state="ok")
        self._copy_button.setEnabled(True)
        self._present()

    def show_error(self, message: str) -> None:
        self._heading.setText("TRANSLATION FAILED")
        self._source.setText("")
        self._set_translation(message, state="error")
        self._copy_button.setEnabled(False)
        self._present()

    def _set_translation(self, text: str, state: str) -> None:
        self._translation.setText(text)
        # Re-polish so the [state="..."] selectors in the stylesheet re-apply.
        self._translation.setProperty("state", state)
        self._translation.style().unpolish(self._translation)
        self._translation.style().polish(self._translation)

    def _present(self) -> None:
        self._fit_height()
        if not self.isVisible():
            self.move(_position_near_cursor(self.width(), self.height()))
        self.show()
        self.raise_()
        self.activateWindow()

    def _fit_height(self) -> None:
        """Grow with the content, up to the configured ceiling, then scroll.

        The space taken by the heading, source line and footer is *measured*
        rather than assumed: the source preview wraps to one or two lines
        depending on the selection, so a hard-coded figure would either clip the
        translation or leave a gap under it.
        """
        # Release every height pinned by the previous translation first. While a
        # fixed height is in force it clamps that widget's own measurements, so
        # heightForWidth() would keep reporting the old text's height and the
        # popup could only ever grow -- a short translation after a long one
        # would inherit the tall window.
        for widget in (self, self._translation):
            widget.setMinimumHeight(0)
            widget.setMaximumHeight(_QWIDGETSIZE_MAX)

        text_height = self._translation.heightForWidth(self._content_width)
        if text_height <= 0:
            text_height = self._translation.sizeHint().height()
        self._translation.setFixedHeight(text_height)

        # Collapse the scroll area, let the layout settle, and read off what
        # everything else costs.
        self._scroll.setFixedHeight(1)
        self._relayout()
        chrome = self.sizeHint().height() - 1

        budget = max(_MIN_TEXT_HEIGHT, self._max_height - chrome)
        # Decide on the scrollbar from the numbers rather than leaving it to
        # "as needed", which shows a bar for a sub-pixel overflow on text that
        # visibly fits.
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if text_height > budget else Qt.ScrollBarAlwaysOff
        )
        self._scroll.setFixedHeight(min(text_height, budget))
        self._relayout()
        self.setFixedHeight(self.sizeHint().height())

    def _relayout(self) -> None:
        """Force both layouts to recompute.

        ``activate()`` alone is not enough: Qt caches each layout's size hint and
        only ``invalidate()`` marks it dirty, so without this the popup keeps
        reporting the height it had for the previous translation.
        """
        for layout in (self._card.layout(), self.layout()):
            layout.invalidate()
            layout.activate()

    def _copy_translation(self) -> None:
        QApplication.clipboard().setText(self._translation.text())
        self._hint.setText("Copied")
        # Put the keyboard hint back, otherwise the only reminder that Esc closes
        # the popup disappears for good after the first copy.
        QTimer.singleShot(1500, lambda: self._hint.setText(_HINT_TEXT))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self.hide()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        self._hint.setText(_HINT_TEXT)
        super().hideEvent(event)


#: Only the two languages this app switches between get a name; anything else
#: shows its ISO code, which is clearer than a wrong guess at the endonym.
_LANGUAGE_LABELS = {"vi": "VIETNAMESE", "en": "ENGLISH"}


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

    # Flip to the other side of the pointer rather than sliding, so the popup
    # never lands under the cursor.
    if x + width > area.right() - _SCREEN_MARGIN:
        x = cursor.x() - width - _CURSOR_OFFSET.x()
    if y + height > area.bottom() - _SCREEN_MARGIN:
        y = cursor.y() - height - _CURSOR_OFFSET.y()

    x = max(area.left() + _SCREEN_MARGIN, min(x, area.right() - width - _SCREEN_MARGIN))
    y = max(area.top() + _SCREEN_MARGIN, min(y, area.bottom() - height - _SCREEN_MARGIN))
    return QPoint(x, y)
