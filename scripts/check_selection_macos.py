"""Manual smoke test for the macOS selection capture.

The macOS counterpart of ``check_selection.py``, and built the same way for the
same reason: it spawns **its own** window in a **separate process**, selects
known text in it, and checks that ``capture_selection`` reads it back and
leaves the clipboard as it found it. It never drives an app you have open.

Posting keystrokes needs Accessibility permission for whatever launched this
script (Terminal, iTerm, ...). Without it the script stops at the first check
and says so. Plain text on the clipboard is put back at the end; an image,
a file or rich text is not.

Run it from the project root:

    .venv.nosync/bin/python scripts/check_selection_macos.py

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import Quartz  # noqa: E402
from AppKit import NSPasteboard, NSPasteboardTypeString  # noqa: E402
from ApplicationServices import AXIsProcessTrusted  # noqa: E402

from wintranslate.selection_macos import (  # noqa: E402
    _write_pasteboard_text,
    capture_selection,
)

SENTINEL = "previous-clipboard-contents-12345"
FIXTURE_TEXT = "Hello world from win-translate"
MULTILINE_TEXT = "First line\nSecond line\nThird line"

KVK_CONTROL = 0x3B
KVK_OPTION = 0x3A

failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global failures
    status = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail and not condition else ""
    print(f"  [{status}] {label}{suffix}")
    if not condition:
        failures += 1


def pasteboard_text() -> str | None:
    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)


def set_pasteboard_text(text: str) -> None:
    _write_pasteboard_text(NSPasteboard.generalPasteboard(), text)


def serve_window(text: str, ready_file: Path) -> int:
    """Child process: show a window holding `text`, fully selected, and wait."""
    from AppKit import NSApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QTextEdit

    app = QApplication([])
    editor = QTextEdit()
    editor.setWindowTitle("win-translate selection fixture")
    editor.setPlainText(text)
    editor.resize(520, 220)
    editor.show()
    # A process started from a terminal is not frontmost by default; Cmd+C goes
    # to the frontmost app, so this one has to take the foreground.
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    editor.raise_()
    editor.activateWindow()
    editor.selectAll()
    editor.setFocus()

    QTimer.singleShot(400, lambda: ready_file.write_text("ready", encoding="utf-8"))
    # Never outlive the parent, even if it crashes.
    QTimer.singleShot(30_000, app.quit)
    return app.exec()


def open_fixture_window(text: str, tmp_dir: Path) -> subprocess.Popen:
    ready_file = tmp_dir / "ready.flag"
    ready_file.unlink(missing_ok=True)

    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()),
         "--serve-window", text, "--ready-file", str(ready_file)]
    )  # fmt: skip

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if ready_file.exists():
            time.sleep(0.4)  # let the window settle into the foreground
            return process
        if process.poll() is not None:
            raise RuntimeError("fixture window exited before it was ready")
        time.sleep(0.1)
    process.kill()
    raise RuntimeError("fixture window never signalled ready")


def post_modifiers(key_down: bool) -> None:
    """Press or release Control+Option as if from the keyboard.

    Uses the *combined* session state, unlike the capture code's private
    source, so the window server treats these as the user's own keys.
    """
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    flags = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
    for key in (KVK_CONTROL, KVK_OPTION):
        event = Quartz.CGEventCreateKeyboardEvent(source, key, key_down)
        Quartz.CGEventSetFlags(event, flags if key_down else 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def main() -> int:
    """Run the checks, then hand the user back the clipboard they had."""
    board = NSPasteboard.generalPasteboard()
    saved = pasteboard_text()
    count_before = board.changeCount()
    try:
        return run_checks()
    finally:
        # Only when a check actually wrote to it; None empties the board rather
        # than leaving the sentinel behind.
        if board.changeCount() != count_before:
            _write_pasteboard_text(board, saved)


def run_checks() -> int:
    tmp_dir = Path(__file__).resolve().parent.parent / ".pytest_cache" / "selection"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print("0. Accessibility permission")
    check("this process may post keystrokes", bool(AXIsProcessTrusted()),
          "enable your terminal under System Settings > Privacy & Security > "
          "Accessibility, then run again")  # fmt: skip
    if failures:
        return 1

    print("\n1. Pasteboard read/write round-trip")
    set_pasteboard_text(SENTINEL)
    check("writes then reads the same text", pasteboard_text() == SENTINEL)

    print("\n2. Capture from a real window in another process")
    window = open_fixture_window(FIXTURE_TEXT, tmp_dir)
    try:
        set_pasteboard_text(SENTINEL)
        captured = capture_selection()
        check("captured the selected text", captured.strip() == FIXTURE_TEXT,
              f"got {captured.strip()!r}")  # fmt: skip
        check("restored the previous clipboard", pasteboard_text() == SENTINEL,
              f"got {pasteboard_text()!r}")  # fmt: skip

        print("\n3. Capture while the hotkey's modifiers are held")
        # The user is still holding Control+Option when the hotkey fires; if
        # they leaked into the copy it would arrive as Ctrl+Opt+Cmd+C.
        post_modifiers(key_down=True)
        try:
            held = capture_selection()
        finally:
            post_modifiers(key_down=False)
        check("still copies with Control and Option held", held.strip() == FIXTURE_TEXT,
              f"got {held.strip()!r}")  # fmt: skip
    finally:
        window.kill()
        window.wait(timeout=5)

    print("\n4. Multi-line selection survives the round-trip")
    window = open_fixture_window(MULTILINE_TEXT, tmp_dir)
    try:
        captured = capture_selection()
        check("newlines preserved", captured.strip().count("\n") == 2,
              f"got {captured.strip()!r}")  # fmt: skip
    finally:
        window.kill()
        window.wait(timeout=5)

    print("\n5. Nothing selected")
    window = open_fixture_window("", tmp_dir)
    try:
        set_pasteboard_text(SENTINEL)
        empty = capture_selection()
        check("returns empty rather than the stale clipboard", empty.strip() == "",
              f"got {empty.strip()!r}")  # fmt: skip
    finally:
        window.kill()
        window.wait(timeout=5)

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-window")
    parser.add_argument("--ready-file")
    args = parser.parse_args()

    if args.serve_window is not None:
        sys.exit(serve_window(args.serve_window, Path(args.ready_file)))
    sys.exit(main())
