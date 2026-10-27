import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="exercises the Win32 clipboard path"
)

TERMINAL = 101
OTHER_APP = 202
PIDS = {TERMINAL: 800, OTHER_APP: 900}
PARENTS = {600: 700, 700: 800, 500: 4}


@pytest.fixture
def selection():
    from wintranslate import selection

    return selection


@pytest.fixture
def desktop(selection, monkeypatch):
    state = {"sequence": 1, "text": "copied earlier", "foreground": TERMINAL, "owner": 0, "copies": None, "sent": []}

    def send(events):
        state["sent"].extend(event.ki.wVk for event in events)
        if state["copies"] is not None:
            copy(state["copies"])

    def copy(text):
        state["sequence"] += 1
        state["text"] = text

    def write(text):
        copy(text)
        state["owner"] = 0

    monkeypatch.setattr(selection.user32, "GetClipboardSequenceNumber", lambda: state["sequence"])
    monkeypatch.setattr(selection.user32, "GetForegroundWindow", lambda: state["foreground"])
    monkeypatch.setattr(selection, "_clipboard_owner_pid", lambda: state["owner"])
    monkeypatch.setattr(selection, "_window_pid", lambda hwnd: PIDS.get(hwnd, 0))
    monkeypatch.setattr(selection, "_process_parents", lambda: PARENTS)
    monkeypatch.setattr(selection, "_read_clipboard_text", lambda: state["text"])
    monkeypatch.setattr(selection, "_write_clipboard_text", write)
    state["write"] = write
    monkeypatch.setattr(selection, "_held_modifiers", lambda: [])
    monkeypatch.setattr(selection, "_send", send)
    monkeypatch.setattr(selection, "_COPY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(selection, "_focus", selection._FocusWatch())
    state["copy"] = copy
    return state


def focus(selection, desktop, hwnd):
    desktop["foreground"] = hwnd
    selection._focus.focus(hwnd)


class TestARealSelection:
    def test_is_copied_with_ctrl_c_and_the_clipboard_restored(self, selection, desktop):
        focus(selection, desktop, OTHER_APP)
        desktop["copies"] = "selected text"
        assert selection.capture_selection() == "selected text"
        assert selection.VK_C in desktop["sent"]
        assert desktop["text"] == "copied earlier"

    def test_its_restore_is_not_taken_for_a_copy_on_the_next_press(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copies"] = "selected text"
        selection.capture_selection()
        desktop["copies"] = None
        assert selection.capture_selection() == ""

    def test_its_restore_is_ignored_even_without_the_rebase(self, selection, desktop, monkeypatch):
        focus(selection, desktop, TERMINAL)
        monkeypatch.setattr(selection._focus, "rebase", lambda hwnd: None)
        desktop["copies"] = "selected text"
        selection.capture_selection()
        desktop["copies"] = None
        assert selection.capture_selection() == ""

    def test_wins_over_a_copy_made_earlier_in_the_same_window(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("an earlier copy")
        desktop["copies"] = "the new selection"
        assert selection.capture_selection() == "the new selection"


class TestACopyOnSelectApp:
    def test_its_copy_is_used_when_ctrl_c_copies_nothing(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("selected in Claude Code")
        assert selection.capture_selection() == "selected in Claude Code"

    def test_its_copy_is_used_when_a_child_process_of_the_window_made_it(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("copied by Claude Code through PowerShell")
        desktop["owner"] = 600
        assert selection.capture_selection() == "copied by Claude Code through PowerShell"

    def test_its_copy_is_used_once_not_on_every_later_press(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("selected in Claude Code")
        selection.capture_selection()
        assert selection.capture_selection() == ""

    def test_its_copy_is_not_reused_after_the_keystroke_fails(self, selection, desktop, monkeypatch):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("selected in Claude Code")

        def blocked(events):
            raise selection.SelectionError("blocked")

        monkeypatch.setattr(selection, "_send", blocked)
        with pytest.raises(selection.SelectionError):
            selection.capture_selection()
        monkeypatch.setattr(selection, "_send", lambda events: None)
        assert selection.capture_selection() == ""


class TestCopiesThatAreNotTheSelection:
    def test_a_copy_made_in_another_app_before_focusing_is_ignored(self, selection, desktop):
        focus(selection, desktop, OTHER_APP)
        desktop["copy"]("hunter2-my-actual-password")
        focus(selection, desktop, TERMINAL)
        assert selection.capture_selection() == ""

    def test_a_copy_from_a_window_that_lost_focus_is_ignored(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("copied in the terminal")
        focus(selection, desktop, OTHER_APP)
        assert selection.capture_selection() == ""

    def test_a_background_copy_by_another_running_app_is_ignored(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("hunter2-my-actual-password")
        desktop["owner"] = 500
        assert selection.capture_selection() == ""

    def test_our_own_popup_copy_is_ignored(self, selection, desktop):
        focus(selection, desktop, TERMINAL)
        desktop["copy"]("the previous translation")
        desktop["owner"] = os.getpid()
        assert selection.capture_selection() == ""

    def test_nothing_is_used_before_the_watch_has_seen_a_focus(self, selection, desktop):
        desktop["copy"]("copied before start")
        assert selection.capture_selection() == ""

    def test_a_press_never_marks_a_window_as_focused_on_its_own(self, selection, desktop):
        selection.capture_selection()
        desktop["copy"]("hunter2-my-actual-password")
        assert selection.capture_selection() == ""


class TestProcessTree:
    def test_reads_the_real_parent_of_this_process(self, selection):
        parents = selection._process_parents()
        assert parents[os.getpid()] == os.getppid()
        assert selection._descends_from(os.getpid(), os.getppid(), parents)
        assert not selection._descends_from(os.getppid(), os.getpid(), parents)

    def test_a_parent_loop_ends(self, selection):
        assert not selection._descends_from(1, 99, {1: 2, 2: 1})


class TestFocusWatch:
    def test_installs_its_hook_and_stops_its_thread(self, selection):
        watch = selection._FocusWatch()
        watch.start()
        thread = watch._thread
        assert thread.is_alive()
        assert watch._hook
        watch.stop()
        assert not thread.is_alive()
        assert watch._hook is None

    def test_a_foreground_event_moves_the_focus(self, selection, desktop):
        watch = selection._focus
        watch._on_foreground(None, selection.EVENT_SYSTEM_FOREGROUND, OTHER_APP, 0, 0, 0, 0)
        desktop["foreground"] = OTHER_APP
        desktop["copy"]("copied in the other app")
        assert selection.capture_selection() == "copied in the other app"


class TestCaptureLock:
    def test_two_captures_never_overlap(self, selection, desktop, monkeypatch):
        import threading

        inside, overlaps = [], []

        def send(events):
            overlaps.append(len(inside))
            inside.append(1)
            threading.Event().wait(0.05)
            inside.pop()

        monkeypatch.setattr(selection, "_send", send)
        threads = [threading.Thread(target=selection.capture_selection) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert overlaps == [0, 0]
