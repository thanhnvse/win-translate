"""The settings window, opened from the tray menu.

Four settings, in the order someone reaches for them: the hotkey, the language
to translate into, the popup's size, and then theme and the detected-language
switch sharing a row. Every change applies immediately -- the app has no
restart step, and a settings window that needed one would be the same trap as
editing the JSON by hand.

Applying is the caller's job: the dialog hands a new
:class:`~wintranslate.config.Config` to ``apply`` and shows whatever message
comes back, so a hotkey another program already owns reports itself here rather
than failing silently.

The window keeps its native frame on purpose. A frameless pane would match the
popup more closely but would take the title bar and taskbar icon with it, and
those are how the window is found again once it is behind something.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import flags, theme as theming
from .config import Config
from .languages import LANGUAGES

#: Qt names these keys; the hotkey parser names them the same way.
_NAMED_KEYS = {
    Qt.Key_Space: "space",
    Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter",
    Qt.Key_Tab: "tab",
    Qt.Key_Escape: "escape",
    Qt.Key_Insert: "insert",
    Qt.Key_Delete: "delete",
    Qt.Key_Home: "home",
    Qt.Key_End: "end",
    Qt.Key_PageUp: "pageup",
    Qt.Key_PageDown: "pagedown",
    Qt.Key_Left: "left",
    Qt.Key_Up: "up",
    Qt.Key_Right: "right",
    Qt.Key_Down: "down",
}

#: Pressing one of these alone is the user still reaching for the rest of it.
_MODIFIER_KEYS = {
    Qt.Key_Control,
    Qt.Key_Alt,
    Qt.Key_Shift,
    Qt.Key_Meta,
    Qt.Key_AltGr,
    Qt.Key_CapsLock,
}

_CONTROL_HEIGHT = 34

#: Every field is this wide, including the two spin boxes plus the gap between
#: them, so one right edge runs down the window.
_CONTROL_WIDTH = 230
_SPIN_GAP = 8

#: A fixed step from a label to its field. A stretch instead would shove the
#: field to the far edge and open a gap the width of the window.
_LABEL_GAP = 22


def qt_to_spec(key: int, modifiers: Qt.KeyboardModifiers) -> str | None:
    """Turn a Qt key event into the hotkey string the parser reads.

    Returns ``None`` while the combination is not usable yet -- a bare modifier,
    or a key with no modifier at all, which the parser rejects anyway because it
    would swallow that key for every application.
    """
    if key in _MODIFIER_KEYS:
        return None

    parts = []
    if modifiers & Qt.ControlModifier:
        parts.append("ctrl")
    if modifiers & Qt.AltModifier:
        parts.append("alt")
    if modifiers & Qt.ShiftModifier:
        parts.append("shift")
    if modifiers & Qt.MetaModifier:
        parts.append("win")
    if not parts:
        return None

    if Qt.Key_F1 <= key <= Qt.Key_F24:
        parts.append(f"f{key - Qt.Key_F1 + 1}")
    elif key in _NAMED_KEYS:
        parts.append(_NAMED_KEYS[key])
    elif 0x20 < key < 0x7F and chr(key).isalnum():
        parts.append(chr(key).lower())
    else:
        return None

    return "+".join(parts)


def pretty(spec: str) -> str:
    """``ctrl+alt+t`` as ``Ctrl + Alt + T``, for showing back to the user."""
    return " + ".join(part.capitalize() for part in spec.split("+") if part)


class HotkeyEdit(QPushButton):
    """Records a key combination by having the user press it."""

    captured = Signal(str)
    rejected = Signal(str)

    def __init__(self, spec: str) -> None:
        super().__init__(objectName="hotkey")
        self._spec = spec
        self._recording = False
        self.setCheckable(True)
        self.setFixedHeight(_CONTROL_HEIGHT)
        self.clicked.connect(self._toggle)
        self._refresh()

    def spec(self) -> str:
        return self._spec

    def set_spec(self, spec: str) -> None:
        self._spec = spec
        self._refresh()

    def _refresh(self) -> None:
        self.setText("Press a combination…" if self._recording else pretty(self._spec))

    def _toggle(self) -> None:
        self._recording = self.isChecked()
        self._refresh()
        if self._recording:
            self.grabKeyboard()
        else:
            self.releaseKeyboard()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Escape and not event.modifiers():
            self._stop()
            return
        spec = qt_to_spec(event.key(), event.modifiers())
        if spec is None:
            event.accept()
            return
        self._spec = spec
        self._stop()
        self.captured.emit(spec)

    def mousePressEvent(self, event) -> None:
        if self._recording:
            # RegisterHotKey accepts a mouse virtual-key and then never delivers
            # WM_HOTKEY for it -- measured: registered=True, fired=0. Accepting
            # one would hand the user a hotkey that silently never works.
            self.rejected.emit("Windows cannot use mouse buttons as a global hotkey.")
            event.accept()
            return
        super().mousePressEvent(event)

    def _stop(self) -> None:
        self._recording = False
        self.setChecked(False)
        self.releaseKeyboard()
        self._refresh()


class ToggleSwitch(QWidget):
    """A switch, because a tick box does not read as on/off at a glance."""

    toggled = Signal(bool)

    def __init__(self, checked: bool, accent: str) -> None:
        super().__init__()
        self._checked = checked
        self._accent = accent
        self._off = "#c7ccd6"
        self.setFixedSize(QSize(44, 26))
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked != self._checked:
            self._checked = checked
            self.update()

    def set_palette(self, accent: str, off: str) -> None:
        self._accent, self._off = accent, off
        self.update()

    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._accent if self._checked else self._off))
        painter.drawRoundedRect(QRectF(0, 0, 44, 26), 13, 13)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(21 if self._checked else 3, 3, 20, 20))


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: Config,
        apply: Callable[[Config], str | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._apply = apply
        self.setWindowTitle("win-translate")
        self.setMinimumWidth(396)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame(objectName="card")
        shell.addWidget(self._card)

        body = QVBoxLayout(self._card)
        pad = theming.CARD_PADDING
        body.setContentsMargins(pad + 2, pad - 4, pad + 2, pad - 4)
        body.setSpacing(0)

        title = QLabel("Settings", objectName="title")
        body.addWidget(title)
        body.addSpacing(16)

        # Row 1 -- the hotkey.
        self._hotkey = HotkeyEdit(config.hotkey)
        self._hotkey.setFixedWidth(_CONTROL_WIDTH)
        self._hotkey.captured.connect(self._on_hotkey)
        self._hotkey.rejected.connect(self._say)
        self._row(body, "Hotkey", self._hotkey, "click, then press the combination")
        self._rule(body)

        # Row 2 -- what to translate into.
        self._language = QComboBox()
        self._language.setIconSize(flags.SIZE)
        self._language.setMaxVisibleItems(14)
        self._language.setFixedWidth(_CONTROL_WIDTH)
        self._language.setFixedHeight(_CONTROL_HEIGHT)
        for language in sorted(LANGUAGES, key=lambda item: item.name):
            text = language.name
            if language.endonym != language.name:
                text = f"{language.name} — {language.endonym}"
            self._language.addItem(flags.icon(language.region), text, language.code)
        self._select_language(config.target_language)
        self._language.currentIndexChanged.connect(self._on_language)
        self._row(body, "Translate into", self._language)
        self._rule(body)

        # Row 3 -- the popup's size.
        self._width = self._spin(config.popup_width, 280, 1200)
        self._height = self._spin(config.popup_max_height, 200, 1200)
        # Together with the gap these come to _CONTROL_WIDTH exactly, so their
        # outer edges line up with the fields above and below.
        each = (_CONTROL_WIDTH - _SPIN_GAP) // 2
        self._width.setFixedWidth(each)
        self._height.setFixedWidth(_CONTROL_WIDTH - _SPIN_GAP - each)
        size = QWidget()
        size.setFixedWidth(_CONTROL_WIDTH)
        size_line = QHBoxLayout(size)
        size_line.setContentsMargins(0, 0, 0, 0)
        size_line.setSpacing(_SPIN_GAP)
        size_line.addWidget(self._width)
        size_line.addWidget(self._height)
        self._row(body, "Popup size", size)
        self._rule(body)

        # Row 4 -- theme and the switch, half the row each.
        self._theme = QComboBox()
        self._theme.setFixedHeight(_CONTROL_HEIGHT)
        for option in theming.THEMES:
            self._theme.addItem(option.label, option.key)
        self._select_theme(config.theme)
        self._theme.currentIndexChanged.connect(self._on_popup)

        self._detected = ToggleSwitch(
            config.show_detected_language, theming.LIGHT.accent
        )
        self._detected.toggled.connect(self._on_detected)

        self._theme.setFixedWidth(118)
        split = QHBoxLayout()
        split.setSpacing(28)
        split.addLayout(self._half("Theme", self._theme), 1)
        # Shortened: the full "Show detected language" does not fit beside its
        # switch in half a row, and a clipped label is worse than a shorter one.
        split.addLayout(self._half("Show detected", self._detected), 1)
        body.addLayout(split)

        body.addSpacing(6)
        self._status = QLabel(objectName="error")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        body.addSpacing(14)
        foot = QHBoxLayout()
        foot.addStretch(1)
        done = QPushButton("Done", objectName="primary")
        done.setFixedWidth(130)
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        body.addLayout(foot)

        self._restyle()

    # -- construction helpers ----------------------------------------------

    def _spin(self, value: int, low: int, high: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSingleStep(20)
        box.setValue(value)
        box.setFixedHeight(_CONTROL_HEIGHT)
        box.valueChanged.connect(self._on_popup)
        return box

    def _row(
        self, body: QVBoxLayout, text: str, widget: QWidget, hint: str = ""
    ) -> None:
        line = QHBoxLayout()
        line.setSpacing(_LABEL_GAP)
        label = QLabel(text, objectName="label")
        line.addWidget(label)
        line.addStretch(1)
        line.addWidget(widget)
        body.addLayout(line)
        if hint:
            note = QLabel(hint, objectName="hint")
            note.setAlignment(Qt.AlignRight)
            body.addSpacing(4)
            body.addWidget(note)

    def _half(self, text: str, widget: QWidget) -> QHBoxLayout:
        """One side of the shared row, reading label then control.

        The same shape as a full row, so the last line of the window does not
        suddenly stack its labels above its controls.
        """
        line = QHBoxLayout()
        line.setSpacing(_LABEL_GAP)
        line.addWidget(QLabel(text, objectName="label"))
        line.addStretch(1)
        line.addWidget(widget, 0, Qt.AlignVCenter)
        return line

    def _rule(self, body: QVBoxLayout) -> None:
        line = QFrame(objectName="rule")
        line.setFixedHeight(1)
        body.addSpacing(13)
        body.addWidget(line)
        body.addSpacing(13)

    # -- helpers ------------------------------------------------------------

    def config(self) -> Config:
        return self._config

    def _restyle(self) -> None:
        # Always light. The theme setting is about the translation popup, which
        # appears over whatever the user is reading; this window is opened
        # deliberately and gains nothing from following it.
        option = theming.LIGHT
        # The card fills the dialog inside a native frame, so rounding its own
        # corners only shows the dialog background through them.
        flush = "#card { border-radius: 0; border: none; }"
        self.setStyleSheet(theming.settings_stylesheet(option) + flush)
        self._detected.set_palette(option.accent, option.secondary_bg)

    def _select_language(self, code: str) -> None:
        index = self._language.findData(code)
        if index < 0:
            # A code the list does not carry is still a working setting; show it
            # rather than silently moving the user to another language.
            self._language.addItem(flags.icon(None), code.upper(), code)
            index = self._language.count() - 1
        self._language.setCurrentIndex(index)

    def _select_theme(self, key: str) -> None:
        self._theme.setCurrentIndex(max(0, self._theme.findData(theming.get(key).key)))

    def _say(self, message: str) -> None:
        self._status.setText(message)

    def _commit(self, **changes: object) -> bool:
        """Apply a change, keeping the old config when the caller refuses it."""
        candidate = replace(self._config, **changes)
        message = self._apply(candidate)
        if message:
            self._say(message)
            return False
        self._config = candidate
        self._say("")
        self._restyle()
        return True

    # -- row handlers --------------------------------------------------------

    def _on_hotkey(self, spec: str) -> None:
        if not self._commit(hotkey=spec):
            self._hotkey.set_spec(self._config.hotkey)

    def _on_language(self) -> None:
        if not self._commit(target_language=self._language.currentData()):
            self._select_language(self._config.target_language)

    def _on_popup(self) -> None:
        self._commit(
            popup_width=self._width.value(),
            popup_max_height=self._height.value(),
            theme=self._theme.currentData(),
        )

    def _on_detected(self, checked: bool) -> None:
        if not self._commit(show_detected_language=checked):
            self._detected.setChecked(self._config.show_detected_language)
