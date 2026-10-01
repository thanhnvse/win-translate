"""The hotkey path's error handling.

The listener catches exceptions from its callback to keep the message loop
alive, but that log line has nowhere to go under pythonw.exe. These check that
an unexpected failure still reaches the popup, so the hotkey never just does
nothing.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "darwin", reason="exercises the Windows hotkey wiring"
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
