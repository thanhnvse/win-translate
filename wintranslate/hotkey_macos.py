"""A system-wide hotkey on macOS, built on Carbon ``RegisterEventHotKey``.

The macOS counterpart of :mod:`wintranslate.hotkey`, chosen for the same reason:
``RegisterEventHotKey`` only ever reports that one specific combination fired,
whereas the alternatives (``NSEvent`` global monitors, ``CGEventTap``) see every
keystroke the user types. It is also the only one of the three that needs no
Accessibility permission — and it swallows the combination, so the focused app
does not also receive it.

Carbon is deprecated but this corner of it is still what every shipping macOS
hotkey library uses, because Cocoa has no replacement. PyObjC no longer wraps
Carbon, so it is called through ``ctypes``.

Unlike the Win32 version there is no thread of our own: the hot-key event is
delivered through the application's event target, which the Qt/Cocoa event loop
pumps, so ``callback`` runs on the Qt main thread.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Callable

log = logging.getLogger(__name__)

# Carbon modifier masks (Events.h).
CMD_KEY = 0x0100
SHIFT_KEY = 0x0200
OPTION_KEY = 0x0800
CONTROL_KEY = 0x1000

_MODIFIER_NAMES = {
    "ctrl": CONTROL_KEY,
    "control": CONTROL_KEY,
    "alt": OPTION_KEY,
    "option": OPTION_KEY,
    "opt": OPTION_KEY,
    "shift": SHIFT_KEY,
    "cmd": CMD_KEY,
    "command": CMD_KEY,
    # Accepted so a config written on Windows still loads: the Windows key sits
    # where Command does on a Mac keyboard.
    "win": CMD_KEY,
    "super": CMD_KEY,
}

# Virtual key codes are positions on an ANSI keyboard, not characters, so on an
# AZERTY layout "a" names the key labelled Q. This is how every macOS hotkey
# works; Carbon offers nothing layout-aware.
_LETTER_KEYS = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28,
    "n": 0x2D, "m": 0x2E,
}  # fmt: skip

_DIGIT_KEYS = {
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
    "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
}  # fmt: skip

_NAMED_KEYS = {
    "space": 0x31,
    "enter": 0x24,
    "return": 0x24,
    "tab": 0x30,
    "escape": 0x35,
    "esc": 0x35,
    "insert": 0x72,  # the Help key, which occupies Insert's slot
    "delete": 0x75,  # forward delete, matching Windows' VK_DELETE
    "home": 0x73,
    "end": 0x77,
    "pageup": 0x74,
    "pagedown": 0x79,
    "left": 0x7B,
    "right": 0x7C,
    "down": 0x7D,
    "up": 0x7E,
}

# Not contiguous, unlike Win32's VK_F1..VK_F24.
_FUNCTION_KEYS = (
    0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D,
    0x67, 0x6F, 0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F, 0x50, 0x5A,
)  # fmt: skip


def _four_char_code(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


_K_EVENT_CLASS_KEYBOARD = _four_char_code("keyb")
_K_EVENT_HOT_KEY_PRESSED = 5
_K_EVENT_PARAM_DIRECT_OBJECT = _four_char_code("----")
_TYPE_EVENT_HOT_KEY_ID = _four_char_code("hkid")
#: Tags our registration so the handler can tell it from anyone else's.
_SIGNATURE = _four_char_code("WTRN")
_NO_ERR = 0
_EVENT_NOT_HANDLED_ERR = -9874


class HotkeyError(Exception):
    """Raised when a hotkey string is invalid or the OS refused to register it."""


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Turn ``"ctrl+alt+t"`` into the ``(modifiers, key_code)`` pair Carbon wants.

    Accepts the same strings as the Windows parser, plus the Mac names
    ``option``/``opt`` and ``cmd``/``command``.
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
            f"Hotkey {spec!r} needs at least one modifier (ctrl/option/shift/cmd), "
            "otherwise it would swallow that key for every application."
        )

    return modifiers, _key_code(key_name, spec)


def _key_code(key_name: str, spec: str) -> int:
    if key_name in _LETTER_KEYS:
        return _LETTER_KEYS[key_name]
    if key_name in _DIGIT_KEYS:
        return _DIGIT_KEYS[key_name]
    if key_name in _NAMED_KEYS:
        return _NAMED_KEYS[key_name]
    if key_name.startswith("f") and key_name[1:].isdigit():
        number = int(key_name[1:])
        if 1 <= number <= len(_FUNCTION_KEYS):
            return _FUNCTION_KEYS[number - 1]
    raise HotkeyError(f"Unknown key {key_name!r} in {spec!r}.")


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_EventHandlerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


def _load_carbon() -> ctypes.CDLL:
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.GetApplicationEventTarget.argtypes = ()
    carbon.InstallEventHandler.restype = ctypes.c_int32
    carbon.InstallEventHandler.argtypes = (
        ctypes.c_void_p,
        _EventHandlerProc,
        ctypes.c_uint32,
        ctypes.POINTER(_EventTypeSpec),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    carbon.RemoveEventHandler.restype = ctypes.c_int32
    carbon.RemoveEventHandler.argtypes = (ctypes.c_void_p,)
    carbon.RegisterEventHotKey.restype = ctypes.c_int32
    carbon.RegisterEventHotKey.argtypes = (
        ctypes.c_uint32,
        ctypes.c_uint32,
        _EventHotKeyID,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    )
    carbon.UnregisterEventHotKey.restype = ctypes.c_int32
    carbon.UnregisterEventHotKey.argtypes = (ctypes.c_void_p,)
    carbon.GetEventParameter.restype = ctypes.c_int32
    carbon.GetEventParameter.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    return carbon


class HotkeyListener:
    """Registers one hotkey and calls ``callback`` on the main thread each time it fires.

    Same interface as the Win32 listener. ``start`` must be called after the
    ``QApplication`` exists, since that is what brings up the event loop the
    hot-key events arrive through.
    """

    _HOTKEY_ID = 1

    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self.spec = spec
        self._modifiers, self._key_code = parse_hotkey(spec)
        self._callback = callback
        self._carbon: ctypes.CDLL | None = None
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()
        # Carbon keeps only a raw pointer to this; dropping the Python object
        # would leave it calling freed memory.
        self._proc = _EventHandlerProc(self._on_event)

    def start(self) -> None:
        carbon = _load_carbon()
        target = carbon.GetApplicationEventTarget()
        event_type = _EventTypeSpec(_K_EVENT_CLASS_KEYBOARD, _K_EVENT_HOT_KEY_PRESSED)

        status = carbon.InstallEventHandler(
            target, self._proc, 1, ctypes.byref(event_type), None,
            ctypes.byref(self._handler_ref),
        )  # fmt: skip
        if status != _NO_ERR:
            raise HotkeyError(f"Could not install the hot-key handler (OSStatus {status}).")

        status = carbon.RegisterEventHotKey(
            self._key_code, self._modifiers, _EventHotKeyID(_SIGNATURE, self._HOTKEY_ID),
            target, 0, ctypes.byref(self._hotkey_ref),
        )  # fmt: skip
        # Unlike Win32, Carbon only refuses a combination this process already
        # holds; one taken by another app or a system shortcut still returns
        # noErr and simply never fires. So this message cannot blame another app.
        if status != _NO_ERR:
            carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
            raise HotkeyError(
                f"Could not register hotkey {self.spec!r} (OSStatus {status}). "
                "Change it in the config."
            )
        self._carbon = carbon

    def stop(self) -> None:
        if self._carbon is None:
            return
        if self._hotkey_ref:
            self._carbon.UnregisterEventHotKey(self._hotkey_ref)
            self._hotkey_ref = ctypes.c_void_p()
        if self._handler_ref:
            self._carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
        self._carbon = None

    def _on_event(self, _next_handler: int, event: int, _user_data: int) -> int:
        hotkey_id = _EventHotKeyID()
        status = self._carbon.GetEventParameter(
            event, _K_EVENT_PARAM_DIRECT_OBJECT, _TYPE_EVENT_HOT_KEY_ID, None,
            ctypes.sizeof(hotkey_id), None, ctypes.byref(hotkey_id),
        )  # fmt: skip
        if (
            status != _NO_ERR
            or hotkey_id.signature != _SIGNATURE
            or hotkey_id.id != self._HOTKEY_ID
        ):
            return _EVENT_NOT_HANDLED_ERR

        try:
            self._callback()
        except Exception:
            # An exception cannot cross back into Carbon; ctypes would print it to
            # a stderr nobody sees under a background launch. Log it instead.
            log.exception("hotkey callback failed")
        return _NO_ERR
