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
import logging
import os
import threading
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

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

WM_QUIT = 0x0012
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
WINEVENT_OUTOFCONTEXT = 0x0000
EVENT_SYSTEM_FOREGROUND = 0x0003


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


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClipboardOwner.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetWinEventHook.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
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
kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class _FocusWatch:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._written = 0
        self._hook: int | None = None
        self._focus: tuple[int | None, int] = (None, 0)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._callback = WINEVENTPROC(self._on_foreground)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, name="win-translate-focus", daemon=True)
            self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        with self._lock:
            thread, thread_id, self._thread, self._thread_id = self._thread, self._thread_id, None, None
        if thread_id is not None:
            user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
        if thread is not None:
            thread.join(timeout=2)

    def focus(self, hwnd: int | None) -> None:
        with self._lock:
            self._focus = (hwnd, user32.GetClipboardSequenceNumber())

    def rebase(self, hwnd: int | None) -> None:
        with self._lock:
            if hwnd and self._focus[0] == hwnd:
                self._focus = (hwnd, user32.GetClipboardSequenceNumber())

    def wrote(self) -> None:
        with self._lock:
            self._written = user32.GetClipboardSequenceNumber()

    def copied_while_focused(self, hwnd: int | None) -> bool:
        with self._lock:
            (focused, sequence), written = self._focus, self._written
        current = user32.GetClipboardSequenceNumber()
        return bool(hwnd) and hwnd == focused and current not in (sequence, written)

    def _on_foreground(self, hook, event, hwnd, id_object, id_child, thread, time_ms) -> None:
        self.focus(hwnd)

    def _run(self) -> None:
        with self._lock:
            self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._callback, 0, 0, WINEVENT_OUTOFCONTEXT)
        self._hook = hook
        if hook:
            self.focus(user32.GetForegroundWindow())
        else:
            log.warning("Could not watch the foreground window; copies made by CLI apps will not be translated.")
        self._ready.set()
        try:
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) not in (0, -1):
                pass
        finally:
            self._hook = None
            if hook:
                user32.UnhookWinEvent(hook)


_focus = _FocusWatch()
_capture_lock = threading.Lock()


def start_focus_watch() -> None:
    _focus.start()


def stop_focus_watch() -> None:
    _focus.stop()


def _window_pid(hwnd: int | None) -> int:
    pid = wintypes.DWORD()
    return pid.value if hwnd and user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) else 0


def _clipboard_owner_pid() -> int:
    return _window_pid(user32.GetClipboardOwner())


def _process_parents() -> dict[int, int]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, INVALID_HANDLE_VALUE):
        return {}
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        parents = {}
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return parents
    finally:
        kernel32.CloseHandle(snapshot)


def _descends_from(pid: int, ancestor: int, parents: dict[int, int]) -> bool:
    seen = set()
    while pid and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = parents.get(pid, 0)
    return False


def _owned_by(hwnd: int | None) -> bool:
    owner = _clipboard_owner_pid()
    return owner != os.getpid() and (owner == 0 or _descends_from(owner, _window_pid(hwnd), _process_parents()))


def _copied_in(hwnd: int | None) -> bool:
    return _focus.copied_while_focused(hwnd) and _owned_by(hwnd)


def _clipboard_snapshot() -> tuple[int, str | None]:
    sequence = user32.GetClipboardSequenceNumber()
    text = _read_clipboard_text()
    current = user32.GetClipboardSequenceNumber()
    return (sequence, text) if current == sequence else (current, _read_clipboard_text())


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
            "Windows blocked the synthesised keystroke. If the focused application "
            "runs as administrator, win-translate has to as well."
        )


def _held_modifiers() -> list[int]:
    return [vk for vk in _MODIFIER_KEYS if user32.GetAsyncKeyState(vk) & 0x8000]


def _open_clipboard() -> None:
    for _ in range(_CLIPBOARD_OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            return
        time.sleep(_CLIPBOARD_OPEN_DELAY)
    raise SelectionError("Another application is holding the clipboard open.")


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
            raise SelectionError("Could not allocate memory to restore the clipboard.")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise SelectionError("Could not lock the clipboard memory block.")
        try:
            ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
        finally:
            kernel32.GlobalUnlock(handle)
        # Ownership of the handle passes to the clipboard on success, so it must
        # not be freed here.
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)  # still ours: the clipboard did not take it
            raise SelectionError("Could not write the clipboard back.")
    finally:
        user32.CloseClipboard()


def capture_selection() -> str:
    """Return the text selected in the focused application.

    Raises :class:`SelectionError` when the clipboard is unreadable or the
    keystroke could not be delivered. Returns an empty string when the app
    answered the copy but there was nothing selected.
    """
    with _capture_lock:
        return _capture(user32.GetForegroundWindow())


def _capture(foreground: int | None) -> str:
    sequence_before, previous_text = _clipboard_snapshot()

    try:
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
            return (previous_text or "") if _copied_in(foreground) else ""

        selected = _read_clipboard_text() or ""

        try:
            _write_clipboard_text(previous_text)
            _focus.wrote()
        except SelectionError:
            # Losing the old clipboard is annoying but must not sink a translation
            # the user is waiting for.
            pass

        return selected
    finally:
        _focus.rebase(foreground)
