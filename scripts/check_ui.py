r"""Render the interface on whatever platform this runs on, and save the images.

The test suite proves the interface builds and that no platform module leaks
into it, but it cannot judge how the result looks under a different window
manager and a different system font. This draws the real widgets and writes
PNGs next to each other so the two platforms can be compared by eye.

    .venv/bin/python scripts/check_ui.py          # macOS
    .venv\Scripts\python.exe scripts\check_ui.py  # Windows

Writes into .pytest_cache/ui-<platform>/ and prints every path. Opens no
window: everything is drawn off screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SAMPLE_SOURCE = "Chưa commit. Còn hai việc treo: bộ cờ đầy đủ."
SAMPLE_TARGET = "Not committed yet. Two things are still open: the full flag set."


def settle(widget) -> None:
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    QApplication.processEvents()
    widget.adjustSize()
    QApplication.processEvents()


def main() -> int:
    app = QApplication([])

    from wintranslate import flags, theme
    from wintranslate.config import Config
    from wintranslate.popup import TranslationPopup
    from wintranslate.settings import SettingsDialog

    out = ROOT / ".pytest_cache" / f"ui-{sys.platform}"
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    popup = TranslationPopup(width=460, max_height=420, theme="light")
    for option in theme.THEMES:
        popup.apply_appearance(460, 420, option.key)
        popup.show_result(SAMPLE_SOURCE, SAMPLE_TARGET, "vi", target="en")
        path = out / f"popup-{option.key}.png"
        popup.grab().save(str(path))
        written.append(path)
    popup.show_pending(SAMPLE_SOURCE)
    pending_height = popup.height()
    popup.show_result(SAMPLE_SOURCE, SAMPLE_TARGET, "vi", target="en")
    result_height = popup.height()
    popup.hide()

    dialog = SettingsDialog(Config(), lambda config: None)
    settle(dialog)
    path = out / "settings.png"
    dialog.grab().save(str(path))
    written.append(path)
    dialog.close()

    missing = [
        language.code
        for language in __import__(
            "wintranslate.languages", fromlist=["LANGUAGES"]
        ).LANGUAGES
        if flags.icon(language.region).isNull()
    ]

    print(f"platform        : {sys.platform}")
    print(f"system font     : {app.font().family()}")
    print(f"popup pending   : {pending_height}px -> result {result_height}px "
          f"(jump {abs(result_height - pending_height)}px)")
    print(f"settings size   : {dialog.width()}x{dialog.height()}")
    print(f"languages w/o a flag: {missing or 'none'}")
    for path in written:
        print(f"  wrote {path}")
    return 1 if missing else 0


sys.exit(main())
