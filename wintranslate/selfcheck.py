"""A quick check that a packaged build carries everything it needs.

Run as ``win-translate --self-check REPORT``. It touches each piece a frozen
build can silently lose -- a platform module, a Qt plugin, a data file, the CA
bundle for HTTPS -- without showing a window, registering a hotkey or using the
network. Findings go to REPORT, because a windowed .exe has no console, and the
exit status is non-zero when anything is missing, so a release build can stop
before it ships a broken app.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable


def run(report: Path) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841 - widgets need it
    lines: list[str] = []
    failures = 0

    def check(name: str, probe: Callable[[], str]) -> None:
        nonlocal failures
        try:
            lines.append(f"ok   {name}: {probe()}")
        except Exception as exc:  # noqa: BLE001 - every failure is reported and counted
            failures += 1
            lines.append(f"FAIL {name}: {type(exc).__name__}: {exc}")

    check("qt platform", lambda: QApplication.platformName())
    check("platform modules", _platform_modules)
    check("icon", _icon)
    check("flag svg", _flag)
    check("theme assets", _theme_assets)
    check("svg image plugin", _svg_image_plugin)
    check("popup", _popup)
    check("settings window", _settings)
    check("https ca bundle", _ca_bundle)
    check("languages", _languages)

    lines.append(f"{failures} failure(s)")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


def _platform_modules() -> str:
    if sys.platform == "darwin":
        from wintranslate import hotkey_macos, macos, selection_macos  # noqa: F401

        return "hotkey_macos, selection_macos (AppKit, Quartz, ApplicationServices), macos"
    from wintranslate import hotkey, selection  # noqa: F401

    return "hotkey, selection"


def _icon() -> str:
    from wintranslate.app import draw_icon

    image = draw_icon(64).toImage()
    if image.isNull() or image.pixelColor(32, 4).alpha() == 0:
        raise RuntimeError("the icon came out empty")
    return "drawn"


def _flag() -> str:
    from wintranslate import flags

    path = flags.FLAG_DIR / "vn.svg"
    if not path.is_file():
        raise FileNotFoundError(path)
    # _render_svg returns None when Qt cannot read SVG -- the missing-plugin case
    # the list would otherwise hide behind blank placeholders.
    pixmap = flags._render_svg(path)
    if pixmap is None:
        raise RuntimeError(f"Qt could not render {path.name}")
    image = pixmap.toImage()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)
    if centre.alpha() == 0:
        raise RuntimeError(f"{path.name} rendered transparent")
    return f"{len(flags.available())} flags, {path.name} renders"


def _theme_assets() -> str:
    from wintranslate import theme

    missing = [
        name
        for name in ("chevron-down-dim.svg", "chevron-up-light.svg")
        if not (theme.ASSETS / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    return str(theme.ASSETS)


def _svg_image_plugin() -> str:
    # The stylesheet's chevrons load through Qt's image plugins, unlike the
    # flags, which QSvgRenderer draws directly; a build missing the plugin
    # passes the flag check and still shows no arrows.
    from PySide6.QtGui import QImageReader, QPixmap

    from wintranslate import theme

    if b"svg" not in [bytes(f) for f in QImageReader.supportedImageFormats()]:
        raise RuntimeError("Qt has no svg image format plugin")
    chevron = theme.ASSETS / "chevron-down-dim.svg"
    if QPixmap(str(chevron)).isNull():
        raise RuntimeError(f"QPixmap could not load {chevron.name}")
    return "svg"


def _popup() -> str:
    from wintranslate.popup import TranslationPopup

    popup = TranslationPopup()
    popup.deleteLater()
    return "built"


def _settings() -> str:
    from wintranslate.config import Config
    from wintranslate.settings import SettingsDialog

    dialog = SettingsDialog(Config(), lambda config: None)
    dialog.deleteLater()
    return "built"


def _ca_bundle() -> str:
    import requests.certs

    where = Path(requests.certs.where())
    if not where.is_file():
        raise FileNotFoundError(where)
    return where.name


def _languages() -> str:
    from wintranslate.languages import LANGUAGES

    if not LANGUAGES:
        raise RuntimeError("no languages")
    return f"{len(LANGUAGES)} languages"
