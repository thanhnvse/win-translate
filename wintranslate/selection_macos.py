"""Read the text the user currently has selected, in whatever app is frontmost — macOS.

The same clipboard round-trip as :mod:`wintranslate.selection`, with the macOS
equivalents of each Win32 piece:

1. remember the general pasteboard's text,
2. post Cmd+C with ``CGEventPost``,
3. poll ``NSPasteboard.changeCount`` until it moves,
4. read the text, then put the old contents back.

The Accessibility API (``AXSelectedText``) would avoid touching the clipboard,
but Chrome and Electron apps do not answer it reliably — the same reason the
Windows side does not use UI Automation.

Two macOS-specific details:

* **Posting keystrokes needs Accessibility permission.** Without it
  ``CGEventPost`` does not fail — the event is silently dropped — so the check
  is made up front and turned into an error the user can act on.
* **The pasteboard has no lock.** ``changeCount`` moves as soon as the other
  app clears the pasteboard, which can be before it has written anything —
  ``clearContents`` followed by ``writeObjects:`` builds the data afterwards.
  So the text is polled for too, not read once. Windows gets this for free:
  ``OpenClipboard`` fails until the writer has closed it.
* **The hotkey's modifiers are still held.** The Cmd+C events come from a
  *private* event source and carry explicit flags, which is enough for a
  physical keyboard.
* **The first copy can go unanswered.** With a mouse button that Logi Options+
  maps to the hotkey, Chrome ignored the first Cmd+C and answered the second,
  sent 250 ms later — with no key or mouse button held at the time. So Cmd+C is
  sent again while nothing has answered, and each capture logs how many it took.

Known limitation: only text is preserved across the round-trip, as on Windows.
"""

from __future__ import annotations

import logging
import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)

#: ``kVK_ANSI_C``: the physical C key, which is what Cmd+C is bound to on every
#: layout macOS ships.
_KEY_C = 0x08

log = logging.getLogger(__name__)

#: How long to wait for the frontmost app to answer Cmd+C, all attempts together.
_COPY_TIMEOUT_SECONDS = 0.9
#: Cmd+C is sent up to this many times, this far apart, until something answers.
_COPY_ATTEMPTS = 3
_COPY_RETRY_SECONDS = 0.25

_COPY_POLL_INTERVAL = 0.015

ACCESSIBILITY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)

#: macOS checks the permission against the app that started Python, not Python.
ACCESSIBILITY_HOW_TO = (
    "Enable win-translate if you opened the app, otherwise the app you started "
    "it from — Terminal, iTerm, or your editor's terminal — under System "
    "Settings → Privacy & Security → Accessibility, then restart win-translate. "
    "Adding Python itself has no effect."
)


class SelectionError(Exception):
    """Raised when the selected text could not be read."""


def request_accessibility() -> bool:
    """Return whether we may post keystrokes, asking macOS to prompt if not.

    The prompt only appears the first time; after the user has dismissed it,
    macOS stays silent and the setting has to be changed by hand.
    """
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))


def _frontmost_app() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.bundleIdentifier()) if app is not None else "?"


def _post_copy() -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)
    for key_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, _KEY_C, key_down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _write_pasteboard_text(board: NSPasteboard, text: str | None) -> None:
    board.clearContents()
    if text is not None and not board.setString_forType_(text, NSPasteboardTypeString):
        raise SelectionError("Could not write the clipboard back.")


def capture_selection() -> str:
    """Return the text selected in the frontmost application.

    Raises :class:`SelectionError` when the app lacks Accessibility permission.
    Returns an empty string when nothing was selected, or the app ignored Cmd+C.
    """
    if not AXIsProcessTrusted():
        raise SelectionError(
            "macOS has not given win-translate Accessibility permission, which it "
            f"needs to press Cmd+C for you. {ACCESSIBILITY_HOW_TO}"
        )

    board = NSPasteboard.generalPasteboard()
    previous_text = board.stringForType_(NSPasteboardTypeString)
    count_before = board.changeCount()

    frontmost = _frontmost_app()

    # Copying twice is harmless; a copy the app did not take is not.
    deadline = time.monotonic() + _COPY_TIMEOUT_SECONDS
    attempts = 0
    changed = False
    while not changed and time.monotonic() < deadline:
        if attempts < _COPY_ATTEMPTS:
            _post_copy()
            attempts += 1
        retry_at = min(deadline, time.monotonic() + _COPY_RETRY_SECONDS)
        while time.monotonic() < retry_at:
            if board.changeCount() != count_before:
                changed = True
                break
            time.sleep(_COPY_POLL_INTERVAL)

    if not changed:
        # "Nothing was selected" is also what the user sees when every copy was
        # ignored; this line tells the two apart.
        log.warning("Cmd+C got no answer: app=%s attempts=%d", frontmost, attempts)
        return ""
    log.info("Cmd+C answered: app=%s attempts=%d", frontmost, attempts)

    selected = board.stringForType_(NSPasteboardTypeString)
    while selected is None and time.monotonic() < deadline:
        time.sleep(_COPY_POLL_INTERVAL)
        selected = board.stringForType_(NSPasteboardTypeString)

    try:
        _write_pasteboard_text(board, previous_text)
    except SelectionError:
        # Losing the old clipboard is annoying but must not sink a translation
        # the user is waiting for.
        pass

    return str(selected or "")
