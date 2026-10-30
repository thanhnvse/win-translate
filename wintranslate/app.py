"""Wiring: tray icon, hotkey, background work, popup.

Threading model, which the ordering here depends on:

* On Windows the hotkey fires on its own Win32 thread; on macOS it arrives on
  the Qt main thread through the Carbon event target. Either way the selection
  is captured *there*, synchronously, because it has to happen while the other
  application still owns the foreground — showing anything of ours first would
  move focus and the synthesised copy would go to the wrong window.
* The captured text then crosses to the Qt thread as a signal, which is where
  every widget touch happens.
* The HTTP call runs on a third, short-lived thread so a slow network cannot
  freeze the popup that is already on screen.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from itertools import count
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .config import Config, ConfigError, config_path

log = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"

if IS_MACOS:
    from . import macos
    from . import selection_macos as selection
    from .hotkey_macos import HotkeyError, HotkeyListener
else:
    from . import selection
    from .hotkey import HotkeyError, HotkeyListener
from .popup import TranslationPopup
from .translate import TranslateError, Translator

APP_NAME = "win-translate"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
#: Rotated, because the Windows log is a file nobody prunes and INFO writes a
#: line per translation.
_LOG_MAX_BYTES = 512 * 1024

#: Guards against a second copy starting and silently failing to take the hotkey.
_MUTEX_NAME = "Global\\win-translate-single-instance"
_ERROR_ALREADY_EXISTS = 183

#: Long enough for Qt's own launch-time activation to have landed first.
_YIELD_AFTER_LAUNCH_MS = 500

#: Drawn on the icon: a big W with a small "tr" tucked under its right arm,
#: the layout win-voice-over uses for its "vo". Sizes are fractions of the
#: square's side; the overlap is a fraction of the W's own width.
_ICON_LETTER = "W"
_ICON_SUFFIX = "tr"
_ICON_LETTER_SIZE = 0.62
_ICON_SUFFIX_SIZE = 0.30
_ICON_RAISE = 0.06
#: win-voice-over's overlap. The "t" of "tr" rises higher than "vo" and would
#: cut into the W's arm, so it is backed off until this much blue shows
#: between them, in grid units: measured per font, because SF on macOS and
#: Segoe UI on Windows draw a different W.
_ICON_MAX_OVERLAP = 0.16
_ICON_GAP = 1.5
#: win-voice-over's blue (sRGB 37, 99, 235) and corner radius, as a fraction
#: of the side, so the two apps' icons match.
_ICON_BLUE = "#2563eb"
_ICON_RADIUS = 0.22
#: The icon is drawn on this grid, in units, then scaled to the size asked for.
_ICON_GRID = 64


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
            width=config.popup_width,
            max_height=config.popup_max_height,
            theme=config.theme,
        )

        self._requests = count(1)
        #: Only the newest request may paint; a slow earlier one is discarded.
        self._current_request = 0
        self._lock = threading.Lock()

        self._bridge = _Bridge()
        self._bridge.captured.connect(self._on_captured, Qt.QueuedConnection)
        self._bridge.translated.connect(self._on_translated, Qt.QueuedConnection)
        self._bridge.failed.connect(self._on_failed, Qt.QueuedConnection)

        self._settings: object | None = None
        self._tray = self._build_tray()
        self._hotkey = HotkeyListener(config.hotkey, self._on_hotkey)

    def start(self) -> None:
        self._hotkey.start()
        if not IS_MACOS:
            selection.start_focus_watch()
        if IS_MACOS and not selection.request_accessibility():
            _explain_accessibility()
        self._tray.show()
        self._tray.showMessage(
            APP_NAME,
            f"Running in the background. Select text and press {self._config.hotkey}.",
            QSystemTrayIcon.Information,
            4000,
        )
        if IS_MACOS:
            # Qt activates the app as the event loop starts, which would leave
            # keyboard focus on an app with no window. Give it back once that
            # has happened.
            QTimer.singleShot(_YIELD_AFTER_LAUNCH_MS, macos.yield_activation)

    def shutdown(self) -> None:
        self._hotkey.stop()
        if not IS_MACOS:
            selection.stop_focus_watch()
        self._tray.hide()

    # -- tray ---------------------------------------------------------------

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(_tray_icon())
        tray.setToolTip(f"{APP_NAME} — {self._config.hotkey}")

        menu = QMenu()
        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        return tray

    def _open_settings(self) -> None:
        """Open the settings window, or raise the one already open."""
        from .settings import SettingsDialog

        if self._settings is not None:
            self._settings.raise_()
            self._settings.activateWindow()
            return
        dialog = SettingsDialog(self._config, self.apply_config)
        dialog.setWindowIcon(_tray_icon())
        self._settings = dialog
        dialog.finished.connect(self._on_settings_closed)
        dialog.show()

    def _on_settings_closed(self) -> None:
        self._settings = None

    def apply_config(self, config: Config) -> str | None:
        """Adopt ``config`` live, or return why it cannot be adopted.

        The hotkey is the only part that can be refused, because another program
        may already own the combination. It is swapped first and everything else
        follows only once it holds, so a rejected hotkey leaves the app exactly
        as it was rather than half-changed.
        """
        if config.hotkey != self._config.hotkey:
            message = self._swap_hotkey(config.hotkey)
            if message:
                return message

        self._config = config
        self._translator = Translator(
            target_language=config.target_language,
            alternate_language=config.alternate_language,
            api_key=config.google_api_key,
        )
        self._popup.apply_appearance(
            config.popup_width, config.popup_max_height, config.theme
        )
        self._tray.setToolTip(f"{APP_NAME} — {config.hotkey}")
        try:
            config.save()
        except OSError as exc:
            # The setting is live either way; say that it will not survive a
            # restart rather than pretending it was stored.
            return f"Applied, but could not be saved: {exc}"
        return None

    def _swap_hotkey(self, spec: str) -> str | None:
        previous = self._hotkey
        previous.stop()
        candidate = HotkeyListener(spec, self._on_hotkey)
        try:
            candidate.start()
        except HotkeyError as exc:
            restored = HotkeyListener(previous.spec, self._on_hotkey)
            try:
                restored.start()
                self._hotkey = restored
            except HotkeyError:
                # Both are gone; say so plainly instead of leaving the user to
                # discover that no hotkey works any more.
                return f"{exc} The previous hotkey could not be restored either."
            return str(exc)
        self._hotkey = candidate
        return None

    def _open_config(self) -> None:
        path = config_path()
        if IS_MACOS:
            # -t: the default *text* editor, not whatever claims .json.
            subprocess.Popen(["open", "-t", str(path)])
            return
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
            self._capture_and_translate(request_id)
        except selection.SelectionError as exc:
            self._bridge.failed.emit(request_id, str(exc))
        except Exception as exc:  # noqa: BLE001
            # The listener catches this too, but only to keep its message loop
            # alive, and under pythonw.exe its log line is somewhere the user
            # will never think to look. Put it on screen, the way a failed
            # translation already is -- otherwise the hotkey just does nothing.
            log.exception("hotkey handling failed")
            self._bridge.failed.emit(request_id, f"Unexpected error: {exc}")

    def _capture_and_translate(self, request_id: int) -> None:
        text = selection.capture_selection()
        if not text.strip():
            self._bridge.failed.emit(request_id, "Nothing was selected.")
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
    return QIcon(draw_icon(64))


def draw_icon(size: int) -> QPixmap:
    """The blue W with a small "tr", at any size. Also the macOS app icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    # Drawn on a fixed grid and scaled, so every size has the same shape. The
    # square fills the whole of it, as win-voice-over's does; the app-icon
    # build adds Apple's margin around it.
    painter.scale(size / _ICON_GRID, size / _ICON_GRID)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(_ICON_BLUE))
    origin, side = 0.0, float(_ICON_GRID)
    radius = side * _ICON_RADIUS
    painter.drawRoundedRect(origin, origin, side, side, radius, radius)

    # Black rather than ExtraBold: measured on the 256 px app icon it gives a
    # 36 px stroke against win-voice-over's 37 px (macOS "heavy"); ExtraBold
    # gave 35.
    letter = _glyphs(_ICON_LETTER, side * _ICON_LETTER_SIZE, QFont.Black)
    suffix = _glyphs(_ICON_SUFFIX, side * _ICON_SUFFIX_SIZE, QFont.Bold)
    # Placed by the ink of the glyphs, not their advance boxes, so the pair is
    # optically centred whatever the font's side bearings are.
    placed_letter, placed_suffix = _tuck(letter, suffix, origin, side)

    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(placed_letter)
    painter.drawPath(placed_suffix)
    painter.end()

    return pixmap


def _tuck(
    letter: QPainterPath, suffix: QPainterPath, origin: float, side: float
) -> tuple[QPainterPath, QPainterPath]:
    """Place the W and the suffix as a centred pair, the suffix as far under
    the W's right arm as it goes without touching it."""
    letter_ink, suffix_ink = letter.boundingRect(), suffix.boundingRect()
    margin = QPainterPathStroker()
    margin.setWidth(_ICON_GAP * 2)
    margin.setJoinStyle(Qt.RoundJoin)
    steps = 16
    for step in range(steps, -1, -1):
        overlap = letter_ink.width() * _ICON_MAX_OVERLAP * step / steps
        width = letter_ink.width() + suffix_ink.width() - overlap
        letter_left = origin + (side - width) / 2
        letter_top = origin + (side - letter_ink.height()) / 2 - side * _ICON_RAISE
        placed_letter = letter.translated(
            letter_left - letter_ink.left(), letter_top - letter_ink.top()
        )
        placed_suffix = suffix.translated(
            letter_left + letter_ink.width() - overlap - suffix_ink.left(),
            letter_top + letter_ink.height() + side * _ICON_RAISE - suffix_ink.bottom(),
        )
        padded = margin.createStroke(placed_suffix).united(placed_suffix)
        if not placed_letter.intersects(padded):
            break
    return placed_letter, placed_suffix


def _glyphs(text: str, pixel_size: float, weight: QFont.Weight) -> QPainterPath:
    """``text`` as an outline, in the system UI font.

    A pixel size, not a point size: points go through the device's DPI, which
    is 72 for a QPixmap on macOS and 96 on Windows, so the same point size drew
    a different-sized letter on each. The system font because it is always
    installed -- asking for a missing family costs a font-alias scan and a
    warning -- and on macOS it is the one with a heavy enough W.
    """
    font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    font.setPixelSize(round(pixel_size))
    font.setWeight(weight)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    return path


def _claim_single_instance() -> bool:
    """Return ``False`` when another copy already holds the mutex (or lock file)."""
    if IS_MACOS:
        return _claim_lock_file()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


#: Held open for the life of the process; the OS drops the lock when it exits,
#: including on a crash, so there is no stale file to clean up.
_lock_handle = None


def _claim_lock_file() -> bool:
    import fcntl

    global _lock_handle
    path = config_path().parent / "instance.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")  # noqa: SIM115 - must outlive this function
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    _lock_handle = handle
    return True


def _explain_accessibility() -> None:
    answer = QMessageBox.information(
        None,
        APP_NAME,
        f"{APP_NAME} needs Accessibility permission to copy the selected text.\n\n"
        f"{selection.ACCESSIBILITY_HOW_TO}",
        QMessageBox.Open | QMessageBox.Ignore,
    )
    if answer == QMessageBox.Open:
        subprocess.Popen(["open", selection.ACCESSIBILITY_SETTINGS_URL])


def _configure_logging() -> None:
    """stderr everywhere, plus a file on Windows.

    macOS keeps stderr: start.command appends it to
    ~/Library/Logs/win-translate.log. Windows has nowhere for it to go --
    start.cmd runs pythonw.exe, which has no console and no redirection -- so
    anything logged there would be lost, which is the whole reason a log exists.
    """
    logging.basicConfig(level=logging.WARNING, format=_LOG_FORMAT)
    # One line per translation from our own code; libraries stay at WARNING.
    logging.getLogger("wintranslate").setLevel(logging.INFO)
    if IS_MACOS:
        return

    path = config_path().parent / f"{APP_NAME}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=_LOG_MAX_BYTES, backupCount=1, encoding="utf-8"
        )
    except OSError as exc:
        # A missing log is not a reason to refuse to start.
        logging.warning("no log file at %s: %s", path, exc)
        return
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.getLogger().addHandler(handler)


def main() -> int:
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    # Windows groups taskbar entries by this id; without it the settings window
    # is filed under the Python interpreter and shows its icon.
    if not IS_MACOS:
        import ctypes

        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(
            f"{APP_NAME}.tray"
        )
    app.setWindowIcon(_tray_icon())
    # The popup is an ordinary window as far as Qt is concerned; without this the
    # app would exit the first time the user dismisses it.
    app.setQuitOnLastWindowClosed(False)
    if IS_MACOS:
        macos.hide_dock_icon()

    if not _claim_single_instance():
        QMessageBox.information(
            None, APP_NAME, f"{APP_NAME} is already running — look in the "
            + ("menu bar." if IS_MACOS else "system tray.")
        )
        return 0

    # After the instance check: a second copy must not open the same rotating
    # log, or the first copy's rollover fails on Windows.
    _configure_logging()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray was found.")
        return 1

    try:
        config = Config.load()
    except ConfigError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    try:
        # Construction parses the hotkey, so a typo in the config fails here.
        translate_app = TranslateApp(app, config)
        translate_app.start()
    except HotkeyError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    app.aboutToQuit.connect(translate_app.shutdown)
    return app.exec()
