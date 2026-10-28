r"""Print exactly what is on the clipboard, byte for byte.

Run it after copying from the window that misbehaves. It separates "the
terminal put the wrong thing on the clipboard" from "win-translate read it
wrong", which otherwise look identical from the popup.

    .venv\Scripts\python.exe scripts\what_did_i_copy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wintranslate.selection import _read_clipboard_text  # noqa: E402

text = _read_clipboard_text()
if text is None:
    print("The clipboard holds no text at all (an image, files, or nothing).")
    raise SystemExit(1)

print(f"length   : {len(text)} characters")
print(f"verbatim : {text[:300]!r}")
print(f"codepoints: {[hex(ord(c)) for c in text[:12]]}")

mojibake = sum(1 for c in text if 0x2500 <= ord(c) <= 0x25FF or ord(c) in (0x2591, 0x2592))
if mojibake:
    print(
        f"\n{mojibake} box-drawing character(s) present — that is the signature of a"
        "\nconsole code page mangling UTF-8. The terminal copied mojibake; the"
        "\ntranslator never saw your text."
    )
else:
    print("\nNo mojibake signature. The clipboard content looks intact.")
