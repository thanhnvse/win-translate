import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="exercises the Win32 clipboard path"
)


@pytest.fixture
def selection():
    from wintranslate import selection

    return selection


@pytest.fixture
def clipboard(selection, monkeypatch):
    state = {"sequence": 1, "now": 100.0}
    monkeypatch.setattr(selection.user32, "GetClipboardSequenceNumber", lambda: state["sequence"])
    monkeypatch.setattr(selection.time, "monotonic", lambda: state["now"])
    watch = selection._ClipboardWatch()
    monkeypatch.setattr(selection, "_clipboard", watch)
    return state, watch


def keys_of(events):
    return [event.ki.wVk for event in events]


def copy_in_terminal(state, watch):
    state["sequence"] += 1
    watch.poll()


class TestClipboardWatch:
    def test_a_fresh_copy_counts_as_recent(self, clipboard):
        state, watch = clipboard
        copy_in_terminal(state, watch)
        assert watch.changed_recently()

    def test_an_old_copy_does_not(self, selection, clipboard):
        state, watch = clipboard
        copy_in_terminal(state, watch)
        state["now"] += selection._RECENT_COPY_SECONDS + 1
        assert not watch.changed_recently()

    def test_no_copy_since_start_does_not(self, clipboard):
        _, watch = clipboard
        watch.poll()
        assert not watch.changed_recently()

    def test_forget_drops_our_own_clipboard_writes(self, clipboard):
        state, watch = clipboard
        copy_in_terminal(state, watch)
        watch.forget()
        watch.poll()
        assert not watch.changed_recently()


class TestCaptureSelection:
    @pytest.fixture
    def sent(self, selection, monkeypatch):
        events = []
        monkeypatch.setattr(selection, "_send", events.extend)
        monkeypatch.setattr(selection, "_read_clipboard_text", lambda: "selected in the CLI")
        monkeypatch.setattr(selection, "_write_clipboard_text", lambda text: None)
        monkeypatch.setattr(selection, "_COPY_TIMEOUT_SECONDS", 0)
        return events

    def test_a_terminal_with_a_fresh_copy_needs_no_ctrl_c(self, selection, clipboard, sent, monkeypatch):
        monkeypatch.setattr(selection, "_window_class", lambda hwnd: "CASCADIA_HOSTING_WINDOW_CLASS")
        copy_in_terminal(*clipboard)
        assert selection.capture_selection() == "selected in the CLI"
        assert not sent

    def test_a_terminal_without_a_fresh_copy_copies_with_ctrl_insert(self, selection, clipboard, sent, monkeypatch):
        monkeypatch.setattr(selection, "_window_class", lambda hwnd: "ConsoleWindowClass")
        selection.capture_selection()
        assert selection.VK_INSERT in keys_of(sent)
        assert selection.VK_C not in keys_of(sent)

    def test_other_apps_ignore_a_fresh_copy_and_use_ctrl_c(self, selection, clipboard, sent, monkeypatch):
        monkeypatch.setattr(selection, "_window_class", lambda hwnd: "Chrome_WidgetWin_1")
        copy_in_terminal(*clipboard)
        selection.capture_selection()
        assert selection.VK_C in keys_of(sent)
