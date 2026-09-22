"""User configuration, stored as JSON under ``%APPDATA%\\win-translate``."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: Ctrl+Alt+T is the default because it is almost unused on Windows. Ctrl+Shift+T
#: would be a poor choice: a global hotkey outranks an application's own
#: shortcut, so it would take "reopen closed tab" away from every browser.
DEFAULT_HOTKEY = "ctrl+alt+t"


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
        return cls(**{key: value for key, value in raw.items() if key in known})

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
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "win-translate" / "config.json"
