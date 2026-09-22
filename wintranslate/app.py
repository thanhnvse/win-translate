"""Wiring: tray icon, hotkey, background work, popup.

Threading model, which the ordering here depends on:

* The hotkey fires on its own Win32 thread. The selection is captured *there*,
  synchronously, because it has to happen while the other application still owns
  the foreground — showing anything of ours first would move focus and the
  synthesised Ctrl+C would go to the wrong window.
* The captured text then crosses to the Qt thread as a signal, which is where
  every widget touch happens.
* The HTTP call runs on a third, short-lived thread so a slow network cannot
  freeze the popup that is already on screen.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
from itertools import count

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import selection
from .config import Config, ConfigError, config_path
from .hotkey import HotkeyError, HotkeyListener
from .popup import TranslationPopup
from .translate import TranslateError, Translator

APP_NAME = "win-translate"

#: Guards against a second copy starting and silently failing to take the hotkey.
_MUTEX_NAME = "Global\\win-translate-single-instance"
_ERROR_ALREADY_EXISTS = 183

#: Letter drawn on the tray icon.
_TRAY_LETTER = "W"


class _Bridge(QObject):
    """Carries results from worker threads onto the Qt thread."""

    captured = Signal(int, str)
    translated = Signal(int, str, str, object, str)
    failed = Signal(int, str)


class TranslateApp:
    def __init__(self, app: QApplication, config: Config) -> None:
        self._app = app
        self._config = config
        self._translator = Translator(
            target_language=config.target_language,
            alternate_language=config.alternate_language,
            api_key=config.google_api_key,
        )
        self._popup = TranslationPopup(
            width=config.popup_width, max_height=config.popup_max_height
        )

        self._requests = count(1)
        #: Only the newest request may paint; a slow earlier one is discarded.
        self._current_request = 0
        self._lock = threading.Lock()

        self._bridge = _Bridge()
        self._bridge.captured.connect(self._on_captured, Qt.QueuedConnection)
        self._bridge.translated.connect(self._on_translated, Qt.QueuedConnection)
        self._bridge.failed.connect(self._on_failed, Qt.QueuedConnection)

        self._tray = self._build_tray()
        self._hotkey = HotkeyListener(config.hotkey, self._on_hotkey)

    def start(self) -> None:
        self._hotkey.start()
        self._tray.show()
        self._tray.showMessage(
            APP_NAME,
            f"Running in the background. Select text and press {self._config.hotkey}.",
            QSystemTrayIcon.Information,
            4000,
        )

    def shutdown(self) -> None:
        self._hotkey.stop()
        self._tray.hide()

    # -- tray ---------------------------------------------------------------

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(_tray_icon())
        tray.setToolTip(f"{APP_NAME} — {self._config.hotkey}")

        menu = QMenu()
        translate_action = QAction(f"Translate selection ({self._config.hotkey})", menu)
        translate_action.triggered.connect(self._on_hotkey)
        menu.addAction(translate_action)

        config_action = QAction("Open config file", menu)
        config_action.triggered.connect(self._open_config)
        menu.addAction(config_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        return tray

    def _open_config(self) -> None:
        path = config_path()
        try:
            os.startfile(path)  # noqa: S606 - opening the user's own config file
        except OSError:
            subprocess.Popen(["notepad.exe", str(path)])

    # -- pipeline -----------------------------------------------------------

    def _on_hotkey(self) -> None:
        """Runs on the hotkey thread (or the Qt thread, from the tray menu)."""
        with self._lock:
            request_id = next(self._requests)
            self._current_request = request_id

        try:
            text = selection.capture_selection()
        except selection.SelectionError as exc:
            self._bridge.failed.emit(request_id, str(exc))
            return

        if not text.strip():
            self._bridge.failed.emit(
                request_id, "Nothing was selected."
            )
            return

        self._bridge.captured.emit(request_id, text)

        worker = threading.Thread(
            target=self._translate,
            args=(request_id, text),
            name=f"win-translate-request-{request_id}",
            daemon=True,
        )
        worker.start()

    def _translate(self, request_id: int, text: str) -> None:
        try:
            result = self._translator.translate_auto(text)
        except TranslateError as exc:
            self._bridge.failed.emit(request_id, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a crash here would kill the thread silently
            self._bridge.failed.emit(request_id, f"Unexpected error: {exc}")
            return
        self._bridge.translated.emit(
            request_id, text, result.text, result.detected_source, result.target
        )

    def _is_stale(self, request_id: int) -> bool:
        with self._lock:
            return request_id != self._current_request

    def _on_captured(self, request_id: int, text: str) -> None:
        if self._is_stale(request_id):
            return
        self._popup.show_pending(text)

    def _on_translated(
        self,
        request_id: int,
        source: str,
        translated: str,
        detected: object,
        target: str,
    ) -> None:
        if self._is_stale(request_id):
            return
        self._popup.show_result(
            source,
            translated,
            detected if isinstance(detected, str) else None,
            target=target,
            show_detected=self._config.show_detected_language,
        )

    def _on_failed(self, request_id: int, message: str) -> None:
        if self._is_stale(request_id):
            return
        self._popup.show_error(message)


def _tray_icon() -> QIcon:
    """Draw the tray icon rather than shipping a .ico next to the source."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#2f6feb"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)

    painter.setPen(QColor("#ffffff"))
    # W is a wider glyph than most, so it gets a smaller point size to keep the
    # same optical margin inside the rounded square.
    font = QFont("Segoe UI", 26, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, _TRAY_LETTER)
    painter.end()

    return QIcon(pixmap)


def _claim_single_instance() -> bool:
    """Return ``False`` when another copy already holds the mutex."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def main() -> int:
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    # The popup is an ordinary window as far as Qt is concerned; without this the
    # app would exit the first time the user dismisses it.
    app.setQuitOnLastWindowClosed(False)

    if not _claim_single_instance():
        QMessageBox.information(
            None, APP_NAME, f"{APP_NAME} is already running — look in the system tray."
        )
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray was found.")
        return 1

    try:
        config = Config.load()
    except ConfigError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    translate_app = TranslateApp(app, config)
    try:
        translate_app.start()
    except HotkeyError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    app.aboutToQuit.connect(translate_app.shutdown)
    return app.exec()
