"""Manual smoke test for the Win32 selection capture.

The unit tests cannot cover this module: it only means anything against a real
foreground window in a real desktop session. So this script spawns **its own**
window in a **separate process**, puts known text in it, selects it, and checks
that ``capture_selection`` reads it back and leaves the clipboard as it found it.

It deliberately does not drive Notepad or any other application the user might
have open. An earlier version did, and on Windows 11 Notepad restored the user's
previous session -- the script then typed into a document that was not its own.
A test must never use somebody's open work as its fixture.

Run it from the project root:

    .venv\\Scripts\\python.exe scripts\\check_selection.py

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wintranslate.selection import (  # noqa: E402
    _key_event,
    _read_clipboard_text,
    _send,
    _write_clipboard_text,
    capture_selection,
)

SENTINEL = "previous-clipboard-contents-12345"
FIXTURE_TEXT = "Hello world from win-translate"
MULTILINE_TEXT = "First line\nSecond line\nThird line"

VK_LSHIFT = 0xA0
VK_LMENU = 0xA4

failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global failures
    status = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail and not condition else ""
    print(f"  [{status}] {label}{suffix}")
    if not condition:
        failures += 1


def serve_window(text: str, ready_file: Path) -> int:
    """Child process: show a window holding `text`, fully selected, and wait."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QTextEdit

    app = QApplication([])
    editor = QTextEdit()
    editor.setWindowTitle("win-translate selection fixture")
    editor.setPlainText(text)
    editor.resize(520, 220)
    editor.show()
    editor.raise_()
    editor.activateWindow()
    editor.selectAll()
    editor.setFocus()

    # Tell the parent the window is up and focused.
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
    )

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


def main() -> int:
    tmp_dir = Path(__file__).resolve().parent.parent / ".pytest_cache" / "selection"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print("1. Clipboard read/write round-trip")
    _write_clipboard_text(SENTINEL)
    check("writes then reads the same text", _read_clipboard_text() == SENTINEL)

    print("\n2. Capture from a real window in another process")
    window = open_fixture_window(FIXTURE_TEXT, tmp_dir)
    try:
        _write_clipboard_text(SENTINEL)
        captured = capture_selection()
        check("captured the selected text", captured.strip() == FIXTURE_TEXT,
              f"got {captured.strip()!r}")
        check("restored the previous clipboard", _read_clipboard_text() == SENTINEL,
              f"got {_read_clipboard_text()!r}")

        print("\n3. Capture while modifiers are physically held")
        # Reproduces the real case: the user is still holding ctrl+alt when the
        # hotkey fires, so a naive Ctrl+C would arrive as Ctrl+Alt+Shift+C.
        _send([_key_event(VK_LSHIFT, key_up=False), _key_event(VK_LMENU, key_up=False)])
        try:
            held = capture_selection()
        finally:
            _send([_key_event(VK_LSHIFT, key_up=True), _key_event(VK_LMENU, key_up=True)])
        check("still copies with Shift and Alt held", held.strip() == FIXTURE_TEXT,
              f"got {held.strip()!r}")
    finally:
        window.kill()
        window.wait(timeout=5)

    print("\n4. Multi-line selection survives the round-trip")
    window = open_fixture_window(MULTILINE_TEXT, tmp_dir)
    try:
        captured = capture_selection()
        check("newlines preserved", captured.strip().count("\n") == 2,
              f"got {captured.strip()!r}")
    finally:
        window.kill()
        window.wait(timeout=5)

    print("\n5. Nothing selected")
    window = open_fixture_window("", tmp_dir)
    try:
        _write_clipboard_text(SENTINEL)
        empty = capture_selection()
        check("returns empty rather than the stale clipboard", empty.strip() == "",
              f"got {empty.strip()!r}")
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
