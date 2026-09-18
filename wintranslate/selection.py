"""Read the text the user currently has selected, in whatever app has focus.

Windows offers no way to ask another process "what is selected right now".
UI Automation's ``TextPattern`` answers it for some controls, but Chrome and
Electron apps do not expose it reliably, so this module uses the approach every
shipping translator app on Windows uses instead:

1. remember what is on the clipboard,
2. synthesise Ctrl+C into the focused app,
3. wait for the clipboard to actually change,
4. read it, then put the old contents back.

Two details make the difference between this working and working *sometimes*:

* **The hotkey's own modifiers are still physically held down** when we fire.
  Sending Ctrl+C while the user holds Ctrl+Alt means the target app receives
  Ctrl+Alt+C, which is not a copy. Every held modifier is released first.
* **Copying is asynchronous.** A fixed ``sleep`` either truncates on a slow app
  or wastes time on a fast one, so we poll ``GetClipboardSequenceNumber`` and
  return as soon as the value moves.

Known limitation: only text is preserved across the round-trip. If the
clipboard held an image or a file list, it is cleared rather than restored.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_C = 0x43

# The left/right specific codes, because releasing VK_SHIFT does not reliably
# clear a right-shift that is physically down.
_MODIFIER_KEYS = (
    0xA0,  # VK_LSHIFT
    0xA1,  # VK_RSHIFT
    0xA2,  # VK_LCONTROL
    0xA3,  # VK_RCONTROL
    0xA4,  # VK_LMENU  (left Alt)
    0xA5,  # VK_RMENU  (right Alt)
    0x5B,  # VK_LWIN
    0x5C,  # VK_RWIN
)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

#: How long to wait for the focused app to answer Ctrl+C.
_COPY_TIMEOUT_SECONDS = 0.6
_COPY_POLL_INTERVAL = 0.015

#: Another process can hold the clipboard open; a few quick retries clear it.
_CLIPBOARD_OPEN_ATTEMPTS = 8
_CLIPBOARD_OPEN_DELAY = 0.01


class SelectionError(Exception):
    """Raised when the selected text could not be read."""


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL


def _key_event(vk: int, key_up: bool) -> INPUT:
    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.ki = _KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if key_up else 0,
        time=0,
        dwExtraInfo=0,
    )
    return event


def _send(events: list[INPUT]) -> None:
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise SelectionError(
            "Windows chặn việc giả lập bàn phím. "
            "Nếu app đang focus chạy quyền admin, win-translate cũng cần chạy admin."
        )


def _held_modifiers() -> list[int]:
    return [vk for vk in _MODIFIER_KEYS if user32.GetAsyncKeyState(vk) & 0x8000]


def _open_clipboard() -> None:
    for _ in range(_CLIPBOARD_OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            return
        time.sleep(_CLIPBOARD_OPEN_DELAY)
    raise SelectionError("Một ứng dụng khác đang giữ clipboard, không mở được.")


def _read_clipboard_text() -> str | None:
    """Return the clipboard's text, or ``None`` when it holds something else."""
    _open_clipboard()
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.c_wchar_p(pointer).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _write_clipboard_text(text: str | None) -> None:
    """Replace the clipboard with ``text``, or empty it when ``text`` is ``None``."""
    _open_clipboard()
    try:
        user32.EmptyClipboard()
        if text is None:
            return
        # +1 for the terminating NUL, which CF_UNICODETEXT requires.
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise SelectionError("Không cấp phát được bộ nhớ để khôi phục clipboard.")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise SelectionError("Không khoá được vùng nhớ clipboard.")
        try:
            ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
        finally:
            kernel32.GlobalUnlock(handle)
        # Ownership of the handle passes to the clipboard on success, so it must
        # not be freed here.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise SelectionError("Không ghi lại được clipboard.")
    finally:
        user32.CloseClipboard()


def capture_selection() -> str:
    """Return the text selected in the focused application.

    Raises :class:`SelectionError` when the clipboard is unreadable or the
    keystroke could not be delivered. Returns an empty string when the app
    answered the copy but there was nothing selected.
    """
    previous_text = _read_clipboard_text()
    sequence_before = user32.GetClipboardSequenceNumber()

    released = _held_modifiers()
    events = [_key_event(vk, key_up=True) for vk in released]
    events += [
        _key_event(VK_CONTROL, key_up=False),
        _key_event(VK_C, key_up=False),
        _key_event(VK_C, key_up=True),
        _key_event(VK_CONTROL, key_up=True),
    ]
    _send(events)

    deadline = time.monotonic() + _COPY_TIMEOUT_SECONDS
    changed = False
    while time.monotonic() < deadline:
        if user32.GetClipboardSequenceNumber() != sequence_before:
            changed = True
            break
        time.sleep(_COPY_POLL_INTERVAL)

    if not changed:
        # The app ignored Ctrl+C. Nothing was selected, or it is a control that
        # does not support copying; either way there is nothing to translate.
        return ""

    selected = _read_clipboard_text() or ""

    try:
        _write_clipboard_text(previous_text)
    except SelectionError:
        # Losing the old clipboard is annoying but must not sink a translation
        # the user is waiting for.
        pass

    return selected
