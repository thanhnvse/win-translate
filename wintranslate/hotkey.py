"""A system-wide hotkey, built on Win32 ``RegisterHotKey``.

``RegisterHotKey`` is deliberate rather than a low-level keyboard hook: a hook
sees every keystroke the user types (including passwords) and needs elevation to
watch elevated apps, whereas ``RegisterHotKey`` only ever tells us that one
specific combination fired. Less power, far less to get wrong.

The registration is bound to the thread that makes it, and the resulting
``WM_HOTKEY`` lands in that thread's message queue, so this class owns a thread
with a plain ``GetMessage`` loop. That also keeps the hotkey working while the
Qt event loop is busy.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
#: Without this, holding the combination repeats at the keyboard's repeat rate.
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODIFIER_NAMES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}


class HotkeyError(Exception):
    """Raised when a hotkey string is invalid or the OS refused to register it."""


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Turn ``"ctrl+alt+t"`` into the ``(modifiers, virtual_key)`` pair Win32 wants.

    Raises :class:`HotkeyError` on anything unparseable, so a typo in the config
    file surfaces at startup rather than as a hotkey that silently never fires.
    """
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise HotkeyError(f"Empty hotkey: {spec!r}")

    *modifier_names, key_name = parts

    modifiers = 0
    for name in modifier_names:
        if name not in _MODIFIER_NAMES:
            raise HotkeyError(f"Unknown modifier {name!r} in {spec!r}.")
        modifiers |= _MODIFIER_NAMES[name]

    if not modifiers:
        raise HotkeyError(
            f"Hotkey {spec!r} needs at least one modifier (ctrl/alt/shift/win), "
            "otherwise it would swallow that key for every application."
        )

    virtual_key = _virtual_key(key_name, spec)
    return modifiers | MOD_NOREPEAT, virtual_key


def _virtual_key(key_name: str, spec: str) -> int:
    if len(key_name) == 1 and key_name.isalnum():
        return ord(key_name.upper())
    if key_name in _NAMED_KEYS:
        return _NAMED_KEYS[key_name]
    if key_name.startswith("f") and key_name[1:].isdigit():
        number = int(key_name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    raise HotkeyError(f"Unknown key {key_name!r} in {spec!r}.")


class HotkeyListener:
    """Registers one hotkey and calls ``callback`` on its own thread each time it fires."""

    _HOTKEY_ID = 1

    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self.spec = spec
        self._modifiers, self._virtual_key = parse_hotkey(spec)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self) -> None:
        """Start listening, blocking until the hotkey is registered or has failed."""
        self._thread = threading.Thread(
            target=self._run, name="win-translate-hotkey", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._error is not None:
            raise self._error
        if not self._ready.is_set():
            raise HotkeyError("The hotkey thread failed to start.")

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(
            None, self._HOTKEY_ID, self._modifiers, self._virtual_key
        ):
            self._error = HotkeyError(
                f"Could not register hotkey {self.spec!r} — most likely another "
                "application already owns this combination. Change it in the config."
            )
            self._ready.set()
            return

        self._ready.set()
        try:
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result in (0, -1):  # WM_QUIT, or an error we cannot recover from
                    break
                if (
                    message.message == WM_HOTKEY
                    and message.wParam == self._HOTKEY_ID
                ):
                    self._callback()
        finally:
            user32.UnregisterHotKey(None, self._HOTKEY_ID)
