"""Flag icons for the language list.

Windows cannot render flag emoji: Segoe UI Emoji has no glyphs for regional
indicator pairs, so "\U0001F1FB\U0001F1F3" draws as the letters VN. Measured with
QFontMetrics.inFont on Windows 11 -- every flag reports False. Flags therefore
have to be real images.

This module looks for ``assets/flags/<region>.svg`` next to the package and
draws a blank placeholder when there is none, so the list is complete from the
first run and gains real flags as assets are added. Languages with no
defensible country -- Arabic, Esperanto, Kurdish -- keep the placeholder
permanently, which is the intended look rather than a gap.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: 4:3, the proportion most flags are drawn at; a fixed box keeps the list from
#: jittering between wide and square flags.
SIZE = QSize(24, 18)

FLAG_DIR = Path(__file__).resolve().parent.parent / "assets" / "flags"


def _placeholder(outline: str) -> QPixmap:
    """A blank flag: the shape, with nothing claimed about whose it is."""
    pixmap = QPixmap(SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor(outline))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(0.5, 0.5, SIZE.width() - 1, SIZE.height() - 1), 2, 2)
    painter.end()
    return pixmap


def _render_svg(path: Path) -> QPixmap | None:
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, SIZE.width(), SIZE.height()))
    painter.end()
    return pixmap


@lru_cache(maxsize=256)
def icon(region: str | None, outline: str = "#55585f") -> QIcon:
    """Return the flag for ``region``, or a blank one.

    Cached because a 109-row list would otherwise re-read and re-rasterise the
    same handful of files every time the dropdown opens.
    """
    if region:
        path = FLAG_DIR / f"{region.lower()}.svg"
        if path.is_file():
            pixmap = _render_svg(path)
            if pixmap is not None:
                return QIcon(pixmap)
    return QIcon(_placeholder(outline))


def available() -> set[str]:
    """Region codes that have an asset, upper-cased. Empty until any are added."""
    if not FLAG_DIR.is_dir():
        return set()
    return {path.stem.upper() for path in FLAG_DIR.glob("*.svg")}
