"""Colours and the stylesheets built from them.

The look is the "frosted alert": a pane with a large corner radius, a soft wide
shadow instead of a hard border, a bold line of text, and equal pill buttons at
the bottom. Geometry is the same in every theme; only the palette changes, so
switching theme cannot break the layout.

Contrast is the thing to watch here. The popup once shipped with near-white
text on a white viewport, so every text token is checked against its own card
in the tests rather than eyeballed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "ui"

#: Shadow geometry, shared by the popup and the settings window.
SHADOW_BLUR = 54
SHADOW_OFFSET = (0, 10)
#: The layout has to leave this much room or the shadow is clipped at the edge.
SHADOW_MARGIN = 24

RADIUS = 20
CARD_PADDING = 22


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    card: str
    rim: str
    shadow: str
    shadow_alpha: int
    title: str
    dim: str
    text: str
    error: str
    accent: str
    divider: str
    control: str
    control_rim: str
    primary_bg: str
    primary_fg: str
    secondary_bg: str
    secondary_fg: str
    scrollbar: str
    #: Which chevron asset reads on this theme's controls.
    chevron: str


LIGHT = Theme(
    key="light",
    label="Light",
    card=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1,"
        " stop:0 #fdfeff, stop:0.55 #f3f6fb, stop:1 #e8eff9)"
    ),
    rim="rgba(255,255,255,0.95)",
    shadow="#8fa3c8",
    shadow_alpha=150,
    title="#101114",
    dim="#6b7280",
    text="#15171c",
    error="#b3261e",
    accent="#0a84ff",
    divider="rgba(16,17,20,0.08)",
    control="#ffffff",
    control_rim="rgba(16,17,20,0.12)",
    primary_bg="#0a84ff",
    primary_fg="#ffffff",
    secondary_bg="#e9ecf2",
    secondary_fg="#3a3f4a",
    scrollbar="rgba(16,17,20,0.22)",
    chevron="dim",
)

DARK = Theme(
    key="dark",
    label="Dark",
    card=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1,"
        " stop:0 #2a2b31, stop:0.55 #212229, stop:1 #191a1f)"
    ),
    rim="rgba(255,255,255,0.12)",
    shadow="#05060a",
    shadow_alpha=200,
    title="#f7f7f9",
    dim="#9a9ba4",
    text="#f2f3f5",
    error="#ff8a80",
    accent="#0a84ff",
    divider="rgba(255,255,255,0.09)",
    control="#2f3036",
    control_rim="rgba(255,255,255,0.13)",
    primary_bg="#0a84ff",
    primary_fg="#ffffff",
    secondary_bg="#3a3b43",
    secondary_fg="#dcdee4",
    scrollbar="rgba(255,255,255,0.26)",
    chevron="light",
)

COLORFUL = Theme(
    key="colorful",
    label="Colorful",
    card=(
        "qlineargradient(x1:0, y1:0, x2:1, y2:1,"
        " stop:0 #fff1f8, stop:0.5 #eef0ff, stop:1 #e6f7ff)"
    ),
    rim="rgba(255,255,255,0.95)",
    shadow="#9b8fd0",
    shadow_alpha=150,
    title="#1b1640",
    dim="#6d6794",
    text="#1b1740",
    error="#c2185b",
    accent="#7b5bd6",
    divider="rgba(27,23,64,0.09)",
    control="rgba(255,255,255,0.86)",
    control_rim="rgba(27,23,64,0.12)",
    primary_bg="#7b5bd6",
    primary_fg="#ffffff",
    secondary_bg="rgba(255,255,255,0.78)",
    secondary_fg="#3f3a74",
    scrollbar="rgba(27,23,64,0.24)",
    chevron="dim",
)

THEMES: tuple[Theme, ...] = (LIGHT, DARK, COLORFUL)
BY_KEY: dict[str, Theme] = {option.key: option for option in THEMES}
DEFAULT = LIGHT


def get(key: str) -> Theme:
    """Return the theme for ``key``; an unknown one falls back to the default."""
    return BY_KEY.get((key or "").strip().lower(), DEFAULT)


def _chevron(theme: Theme, direction: str) -> str:
    """The asset path, ready to drop into a stylesheet ``url()``.

    Forward slashes because Qt wants them even on Windows, and quoted because
    an unquoted path breaks at the first space -- which any checkout under
    ``~/My Projects`` or ``C:/Users/First Last`` would contain. Without the
    quotes the rule is dropped and the control loses its arrows entirely.
    """
    path = str(ASSETS / f"chevron-{direction}-{theme.chevron}.svg").replace("\\", "/")
    return f'"{path}"'


def _controls(theme: Theme) -> str:
    """Inputs, buttons and the soft spin arrows, shared by both windows."""
    return f"""
QComboBox, QAbstractSpinBox, #hotkey {{
    background: {theme.control};
    color: {theme.text};
    border: 1px solid {theme.control_rim};
    border-radius: 9px;
    padding: 6px 10px;
    font-size: 12px;
    min-height: 18px;
}}
#hotkey {{ font-weight: 600; }}
#hotkey:checked {{ border: 1px solid {theme.accent}; color: {theme.accent}; }}
QComboBox:focus, QAbstractSpinBox:focus, #hotkey:focus {{
    border: 1px solid {theme.accent};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: url({_chevron(theme, "down")});
    width: 12px; height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {theme.control};
    color: {theme.text};
    border: 1px solid {theme.control_rim};
    border-radius: 10px;
    padding: 4px;
    outline: none;
    selection-background-color: {theme.accent};
    selection-color: {theme.primary_fg};
}}
/* Rounded chevrons rather than the default hard triangles, and no dividing
   line between the two halves, so the control reads as one soft shape. */
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    background: transparent;
    border: none;
    width: 20px;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin: 3px 4px 0 0; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin: 0 4px 3px 0; }}
QAbstractSpinBox::up-arrow {{
    image: url({_chevron(theme, "up")});
    width: 12px; height: 10px;
}}
QAbstractSpinBox::down-arrow {{
    image: url({_chevron(theme, "down")});
    width: 12px; height: 10px;
}}
#primary {{
    background: {theme.primary_bg};
    color: {theme.primary_fg};
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-size: 12px;
    font-weight: 600;
}}
#primary:hover {{ background: {theme.accent}; }}
#primary:pressed {{ padding-top: 10px; padding-bottom: 8px; }}
#secondary {{
    background: {theme.secondary_bg};
    color: {theme.secondary_fg};
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-size: 12px;
    font-weight: 600;
}}
#secondary:pressed {{ padding-top: 10px; padding-bottom: 8px; }}
"""


def popup_stylesheet(theme: Theme) -> str:
    return f"""
#card {{
    background: {theme.card};
    border: 1px solid {theme.rim};
    border-radius: {RADIUS}px;
}}
#heading {{
    color: {theme.dim};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}
#translation {{ color: {theme.title}; font-size: 15px; font-weight: 600; }}
#translation[state="error"] {{ color: {theme.error}; font-weight: 600; }}
#translation[state="pending"] {{ color: {theme.dim}; font-weight: 400; font-style: italic; }}
#source {{ color: {theme.dim}; font-size: 11px; }}
{_controls(theme)}
/* The scroll area's viewport is a separate widget with its own palette and
   defaults to QPalette.Base. Without these three selectors the translation is
   drawn on a white block whatever the theme says. */
QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {theme.scrollbar};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def settings_stylesheet(theme: Theme) -> str:
    return f"""
#card {{
    background: {theme.card};
    border: 1px solid {theme.rim};
    border-radius: {RADIUS}px;
}}
#title {{ color: {theme.title}; font-size: 15px; font-weight: 700; }}
#label {{ color: {theme.dim}; font-size: 12px; }}
#hint  {{ color: {theme.dim}; font-size: 10px; }}
#error {{ color: {theme.error}; font-size: 11px; }}
#rule  {{ background: {theme.divider}; }}
{_controls(theme)}
"""
