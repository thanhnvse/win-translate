import json

import pytest

from wintranslate.config import DEFAULT_HOTKEY, Config, ConfigError


class TestConfigLoad:
    def test_writes_defaults_on_first_run(self, tmp_path):
        path = tmp_path / "config.json"
        config = Config.load(path)
        assert config.hotkey == DEFAULT_HOTKEY
        assert config.target_language == "vi"
        assert path.exists(), "first run should leave a file the user can edit"

    def test_reads_back_what_was_saved(self, tmp_path):
        path = tmp_path / "config.json"
        Config(hotkey="ctrl+shift+k", google_api_key="secret").save(path)
        loaded = Config.load(path)
        assert loaded.hotkey == "ctrl+shift+k"
        assert loaded.google_api_key == "secret"

    def test_missing_keys_fall_back_to_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"hotkey": "ctrl+alt+j"}), encoding="utf-8")
        loaded = Config.load(path)
        assert loaded.hotkey == "ctrl+alt+j"
        assert loaded.target_language == "vi"

    def test_unknown_keys_are_ignored(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"hotkey": "ctrl+alt+j", "leftover_setting": 1}),
            encoding="utf-8",
        )
        assert Config.load(path).hotkey == "ctrl+alt+j"

    def test_malformed_json_is_reported_not_overwritten(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"hotkey": ', encoding="utf-8")
        with pytest.raises(ConfigError):
            Config.load(path)
        # An API key pasted in by hand must survive a syntax error elsewhere.
        assert path.read_text(encoding="utf-8") == '{"hotkey": '

    def test_a_json_array_is_rejected(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ConfigError):
            Config.load(path)

    def test_save_creates_missing_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "config.json"
        Config().save(path)
        assert path.exists()

    def test_saved_file_keeps_vietnamese_readable(self, tmp_path):
        path = tmp_path / "config.json"
        Config(target_language="vi").save(path)
        assert "\\u" not in path.read_text(encoding="utf-8")


class TestDefaultHotkey:
    def test_default_is_a_parseable_hotkey_on_this_platform(self):
        import sys

        if sys.platform == "darwin":
            from wintranslate.hotkey_macos import parse_hotkey
        else:
            from wintranslate.hotkey import parse_hotkey
        parse_hotkey(DEFAULT_HOTKEY)  # raises on anything invalid

