"""Colours and the stylesheets built from them.

The look is the "frosted alert": a pane with a large corner radius, a soft wide
shadow instead of a hard border, a bold line of text, and equal pill buttons at
the bottom. Geometry is the same in every theme; only the palette changes, so
switching theme cannot break the layout.

Gradients are kept as **stops**, not as finished ``qlineargradient(...)``
strings. A string can only be checked by sampling the pixels it eventually
paints, and the pixel checks written for this popup have been wrong more often
than the code they tested. Stops can be compared directly, so
``tests/test_settings.py`` measures every text colour against every card colour
and fails on the worst pair rather than on an average of anti-aliased noise.

Contrast is the thing to watch: this popup once shipped with near-white text on
a white viewport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "ui"

#: Shadow geometry, shared by the popup and the settings window.
SHADOW_BLUR = 54
SHADOW_OFFSET = (0, 10)
#: The layout has to leave this much room or the shadow is clipped at the edge.
SHADOW_MARGIN = 24

RADIUS = 20
CARD_PADDING = 22

Stops = tuple[tuple[float, str], ...]


def gradient(stops: Stops, direction: str = "diagonal") -> str:
    """Build a Qt stylesheet gradient. Qt accepts one for ``color`` too, which
    is how the translation carries a gradient without any new painting code."""
    coords = {
        "diagonal": "x1:0, y1:0, x2:1, y2:1",
        "horizontal": "x1:0, y1:0, x2:1, y2:0",
        "vertical": "x1:0, y1:0, x2:0, y2:1",
    }[direction]
    body = ", ".join(f"stop:{at} {colour}" for at, colour in stops)
    return f"qlineargradient({coords}, {body})"


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    card_stops: Stops
    #: Solid colour for headings and for the translation when there is no
    #: gradient. Also the settings window's title.
    title: str
    dim: str
    text: str
    error: str
    accent: str
    rim: str
    shadow: str
    shadow_alpha: int
    divider: str
    control: str
    control_rim: str
    primary_fg: str
    secondary_bg: str
    secondary_fg: str
    scrollbar: str
    #: Which chevron asset reads on this theme's controls.
    chevron: str
    #: Empty means the translation is drawn in `title`.
    text_stops: Stops = ()
    #: Empty means the primary button is filled with `accent`.
    primary_stops: Stops = ()

    @property
    def card(self) -> str:
        return gradient(self.card_stops)

    @property
    def translation_colour(self) -> str:
        return gradient(self.text_stops, "horizontal") if self.text_stops else self.title

    @property
    def primary_bg(self) -> str:
        return gradient(self.primary_stops, "horizontal") if self.primary_stops else self.accent


LIGHT = Theme(
    key="light",
    label="Light",
    card_stops=((0.0, "#fdfeff"), (0.55, "#f3f6fb"), (1.0, "#e8eff9")),
    title="#101114",
    dim="#6b7280",
    text="#15171c",
    error="#b3261e",
    accent="#0a84ff",
    rim="rgba(255,255,255,0.95)",
    shadow="#8fa3c8",
    shadow_alpha=150,
    divider="rgba(16,17,20,0.08)",
    control="#ffffff",
    control_rim="rgba(16,17,20,0.12)",
    primary_fg="#ffffff",
    secondary_bg="#e9ecf2",
    secondary_fg="#3a3f4a",
    scrollbar="rgba(16,17,20,0.22)",
    chevron="dim",
)

DARK = Theme(
    key="dark",
    label="Dark",
    card_stops=((0.0, "#2a2b31"), (0.55, "#212229"), (1.0, "#191a1f")),
    title="#f7f7f9",
    dim="#9a9ba4",
    text="#f2f3f5",
    error="#ff8a80",
    accent="#0a84ff",
    rim="rgba(255,255,255,0.12)",
    shadow="#05060a",
    shadow_alpha=200,
    divider="rgba(255,255,255,0.09)",
    control="#2f3036",
    control_rim="rgba(255,255,255,0.13)",
    primary_fg="#ffffff",
    secondary_bg="#3a3b43",
    secondary_fg="#dcdee4",
    scrollbar="rgba(255,255,255,0.26)",
    chevron="light",
)

#: Pastel card, saturated text. The light theme's quiet greys would disappear
#: on it, so every token here is pulled toward the purple end.
COLORFUL = Theme(
    key="colorful",
    label="Colorful",
    card_stops=(
        (0.0, "#ffeaf6"),
        (0.28, "#f0e7ff"),
        (0.55, "#e4f0ff"),
        (0.8, "#e2fbf3"),
        (1.0, "#fff6e3"),
    ),
    text_stops=(
        (0.0, "#b5179e"),
        (0.4, "#5a189a"),
        (0.72, "#1e6091"),
        (1.0, "#12715a"),
    ),
    primary_stops=((0.0, "#c13bb0"), (1.0, "#5b5bd6")),
    title="#5a189a",
    dim="#8a7f9c",
    text="#2b2345",
    error="#b3123f",
    accent="#c13bb0",
    rim="rgba(255,255,255,0.95)",
    shadow="#b09ccb",
    shadow_alpha=150,
    divider="rgba(27,23,64,0.09)",
    control="rgba(255,255,255,0.86)",
    control_rim="rgba(27,23,64,0.12)",
    primary_fg="#ffffff",
    secondary_bg="rgba(255,255,255,0.80)",
    secondary_fg="#5a4b73",
    scrollbar="rgba(27,23,64,0.24)",
    chevron="dim",
)

#: Near black, so the letters carry all the colour.
NEON = Theme(
    key="neon",
    label="Neon",
    card_stops=(
        (0.0, "#0a0a12"),
        (0.4, "#140f26"),
        (0.72, "#1c1033"),
        (1.0, "#0d1226"),
    ),
    text_stops=(
        (0.0, "#ff4ecd"),
        (0.3, "#b06cff"),
        (0.62, "#4ad7ff"),
        (1.0, "#5affc8"),
    ),
    primary_stops=((0.0, "#ff4ecd"), (1.0, "#4ad7ff")),
    title="#e9d9ff",
    dim="#8f87b8",
    text="#efe9ff",
    error="#ff6b9d",
    accent="#ff4ecd",
    rim="rgba(255,255,255,0.12)",
    shadow="#000008",
    shadow_alpha=210,
    divider="rgba(255,255,255,0.09)",
    control="#1a1630",
    control_rim="rgba(255,255,255,0.14)",
    primary_fg="#0a0a12",
    secondary_bg="rgba(255,255,255,0.08)",
    secondary_fg="#c6bdea",
    scrollbar="rgba(255,255,255,0.26)",
    chevron="light",
)

THEMES: tuple[Theme, ...] = (LIGHT, DARK, COLORFUL, NEON)
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
/* A plain drop-down list rather than the macOS menu-style popup. That one is
   painted as a native menu panel in the system appearance -- near black in Dark
   Mode -- so black bands and corners showed around the light list, and its
   scroll arrows sat on black strips. Windows already shows this kind. */
QComboBox {{ combobox-popup: 0; }}
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
    # The state selectors are more specific than #translation, so a gradient
    # set there does not bleed into the error or waiting states -- those stay
    # one colour, which is what makes them read as not-a-translation.
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
#translation {{ color: {theme.translation_colour}; font-size: 15px; font-weight: 600; }}
#translation[state="error"] {{ color: {theme.error}; font-weight: 600; }}
#translation[state="pending"] {{ color: {theme.dim}; font-weight: 400; font-style: italic; }}
#source {{ color: {theme.dim}; font-size: 11px; }}
{_controls(theme)}
/* The scroll area's viewport is a separate widget with its own palette and
   defaults to QPalette.Base, so without this the translation is drawn on a
   white block whatever the theme says.
   The viewport is named, rather than reached with `QScrollArea > QWidget >
   QWidget`: that selector also matches the translation label inside it, and a
   gradient `color` collapses to its last stop on any widget a background rule
   touches. Measured -- the four-stop text went flat #12715a. */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; border: none; }}
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
