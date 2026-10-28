"""The hotkey path's error handling.

The listener catches exceptions from its callback to keep the message loop
alive, but that log line has nowhere to go under pythonw.exe. These check that
an unexpected failure still reaches the popup, so the hotkey never just does
nothing.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="exercises the Windows hotkey wiring"
)


@pytest.fixture
def translate_app(qapp, tmp_path, monkeypatch):
    from wintranslate.app import TranslateApp
    from wintranslate.config import Config

    # A tray icon is created in __init__; the hotkey is only registered by
    # start(), which these tests do not call.
    app = TranslateApp(qapp, Config())
    yield app
    app._tray.hide()


def failures_from(app, monkeypatch, raised):
    """Call the hotkey handler with capture_selection raising, collect messages."""
    from wintranslate import selection

    seen = []
    app._bridge.failed.connect(lambda _id, message: seen.append(message))

    def boom():
        raise raised

    monkeypatch.setattr(selection, "capture_selection", boom)
    app._on_hotkey()
    return seen


class TestHotkeyErrorsReachTheUser:
    def test_an_unexpected_exception_is_shown_rather_than_swallowed(
        self, translate_app, monkeypatch
    ):
        seen = failures_from(translate_app, monkeypatch, RuntimeError("ctypes blew up"))
        assert seen, "an unexpected error must still reach the popup"
        assert "ctypes blew up" in seen[0]

    def test_a_selection_error_keeps_its_own_message(
        self, translate_app, monkeypatch
    ):
        from wintranslate.selection import SelectionError

        seen = failures_from(
            translate_app, monkeypatch, SelectionError("Clipboard is held open.")
        )
        assert seen == ["Clipboard is held open."]
        assert "Unexpected error" not in seen[0]

    def test_the_handler_does_not_propagate(self, translate_app, monkeypatch):
        """It runs on the listener's thread; escaping would end its loop."""
        failures_from(translate_app, monkeypatch, RuntimeError("boom"))
        # Reaching here without an exception is the assertion.


class TestLogging:
    def test_windows_gets_a_log_file_because_stderr_is_discarded(
        self, tmp_path, monkeypatch
    ):
        import logging

        from wintranslate import app as app_module

        monkeypatch.setattr(app_module, "IS_MACOS", False)
        monkeypatch.setattr(
            app_module, "config_path", lambda: tmp_path / "win-translate" / "config.json"
        )
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            app_module._configure_logging()
            logging.getLogger("wintranslate").error("written to the file")
            for handler in root.handlers:
                handler.flush()
            log = tmp_path / "win-translate" / "win-translate.log"
            assert log.exists(), "pythonw.exe has no console; the file is the only sink"
            assert "written to the file" in log.read_text(encoding="utf-8")
        finally:
            for handler in list(root.handlers):
                if handler not in before:
                    handler.close()
                    root.removeHandler(handler)

    def test_an_unwritable_log_location_does_not_stop_startup(
        self, tmp_path, monkeypatch
    ):
        import logging

        from wintranslate import app as app_module

        monkeypatch.setattr(app_module, "IS_MACOS", False)
        # A file where the directory should be: mkdir raises OSError.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(
            app_module, "config_path", lambda: blocker / "win-translate" / "config.json"
        )
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            app_module._configure_logging()  # must not raise
        finally:
            for handler in list(root.handlers):
                if handler not in before:
                    handler.close()
                    root.removeHandler(handler)


class _FakeListener:
    """Stands in for HotkeyListener so tests never grab a real global hotkey."""

    registered: list[str] = []
    refuse: set[str] = set()

    def __init__(self, spec, callback):
        self.spec, self._callback, self.running = spec, callback, False

    def start(self):
        from wintranslate.hotkey import HotkeyError

        if self.spec in self.refuse:
            raise HotkeyError(f"Could not register hotkey {self.spec!r}.")
        self.running = True
        _FakeListener.registered.append(self.spec)

    def stop(self):
        self.running = False


@pytest.fixture
def fake_hotkeys(monkeypatch):
    from wintranslate import app as app_module

    _FakeListener.registered = []
    _FakeListener.refuse = set()
    monkeypatch.setattr(app_module, "HotkeyListener", _FakeListener)
    return _FakeListener


class TestApplyConfig:
    """Settings apply live; the app has no restart step to fall back on."""

    def test_a_new_target_language_reaches_the_translator(self, translate_app, tmp_path, monkeypatch):
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        assert translate_app.apply_config(
            replace(translate_app._config, target_language="ja")
        ) is None
        assert translate_app._translator.target_language == "ja"

    def test_a_new_theme_restyles_the_popup_without_rebuilding_it(self, translate_app, tmp_path, monkeypatch):
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        popup = translate_app._popup
        translate_app.apply_config(replace(translate_app._config, theme="light"))
        assert translate_app._popup is popup, "the popup object must survive"
        assert popup._theme.key == "light"

    def test_a_new_size_reaches_the_popup(self, translate_app, tmp_path, monkeypatch):
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        translate_app.apply_config(replace(translate_app._config, popup_width=520))
        assert translate_app._popup.width() == 520

    def test_the_change_is_written_so_it_survives_a_restart(self, translate_app, tmp_path, monkeypatch):
        import json
        from dataclasses import replace
        from wintranslate import config as config_module

        path = tmp_path / "c.json"
        monkeypatch.setattr(config_module, "config_path", lambda: path)
        translate_app.apply_config(replace(translate_app._config, target_language="de"))
        assert json.loads(path.read_text(encoding="utf-8"))["target_language"] == "de"


class TestHotkeySwap:
    def test_a_new_hotkey_replaces_the_old_registration(self, translate_app, fake_hotkeys, tmp_path, monkeypatch):
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        assert translate_app.apply_config(
            replace(translate_app._config, hotkey="ctrl+alt+j")
        ) is None
        assert translate_app._hotkey.spec == "ctrl+alt+j"
        assert translate_app._hotkey.running

    def test_a_hotkey_another_program_owns_leaves_the_old_one_working(self, translate_app, fake_hotkeys, tmp_path, monkeypatch):
        """Refusing must not cost the user the hotkey they already had."""
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        fake_hotkeys.refuse = {"ctrl+alt+j"}
        before = translate_app._config
        message = translate_app.apply_config(replace(before, hotkey="ctrl+alt+j"))
        assert message and "ctrl+alt+j" in message
        assert translate_app._hotkey.spec == before.hotkey
        assert translate_app._hotkey.running
        assert translate_app._config is before, "nothing else may change either"

    def test_a_refused_hotkey_does_not_apply_the_rest_of_the_change(self, translate_app, fake_hotkeys, tmp_path, monkeypatch):
        from dataclasses import replace
        from wintranslate import config as config_module

        monkeypatch.setattr(config_module, "config_path", lambda: tmp_path / "c.json")
        fake_hotkeys.refuse = {"ctrl+alt+j"}
        translate_app.apply_config(
            replace(translate_app._config, hotkey="ctrl+alt+j", target_language="ja")
        )
        assert translate_app._translator.target_language != "ja"
