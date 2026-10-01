"""User configuration, stored as JSON under ``%APPDATA%\\win-translate`` on
Windows and ``~/Library/Application Support/win-translate`` on macOS."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: A global hotkey outranks an application's own shortcut, so the default has to
#: be a combination nobody misses. On Windows that rules out Ctrl+T (new tab in
#: every browser) and Ctrl+Shift+T (reopen closed tab), hence Ctrl+Alt+T. On
#: macOS those browser shortcuts use Command, so plain Control+T is free apart
#: from "transpose letters" in text fields, and one modifier is quicker to hit.
DEFAULT_HOTKEY = "ctrl+t" if sys.platform == "darwin" else "ctrl+alt+t"

#: Settings where ``null`` is a reasonable thing to hand-write for "none", and
#: is read as the empty value rather than rejected. Both of these already treat
#: empty as "off" -- no API key, no reverse direction -- so refusing to start
#: over a ``null`` would block a config that behaves exactly as intended.
#: Every other setting stays strict: ``null`` for a hotkey or a popup width has
#: no meaning, and failing early beats a traceback later.
_NULL_MEANS_EMPTY = frozenset({"alternate_language", "google_api_key"})


@dataclass
class Config:
    hotkey: str = DEFAULT_HOTKEY
    target_language: str = "vi"
    #: Where text that is *already* in `target_language` gets translated to, so
    #: the same hotkey works both ways. Set it to "" to always translate into
    #: `target_language` and leave Vietnamese selections untouched.
    alternate_language: str = "en"
    #: Empty means the free endpoint. Set this to use Cloud Translation API v2.
    google_api_key: str = ""
    popup_width: int = 460
    popup_max_height: int = 420
    #: Show the language Google detected on the source text.
    show_detected_language: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Read the config file, falling back to defaults for anything missing.

        A malformed file is reported rather than silently replaced — overwriting
        it would throw away an API key the user pasted in by hand.
        """
        path = path or config_path()
        if not path.exists():
            config = cls()
            config.save(path)
            return config

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Could not read the config at {path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(f"The config at {path} must be a JSON object.")

        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        # A wrong type would otherwise surface far from here, as a traceback.
        defaults = cls()
        for key, value in list(values.items()):
            if value is None and key in _NULL_MEANS_EMPTY:
                values[key] = ""
                continue
            expected = type(getattr(defaults, key))
            if type(value) is not expected:  # not isinstance: True must not pass as an int
                raise ConfigError(
                    f"{key!r} in {path} must be a {expected.__name__}, "
                    f"not {type(value).__name__}."
                )
        return cls(**values)

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


class ConfigError(Exception):
    """Raised when the config file exists but cannot be used."""


def config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "win-translate" / "config.json"
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "win-translate" / "config.json"
