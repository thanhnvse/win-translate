"""The macOS capture logic, against a fake pasteboard.

Nothing here touches the real clipboard or posts a keystroke: the pasteboard,
the Cmd+C and the permission check are all replaced. What is left is the part
that has to be right regardless — polling, reading, restoring.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("AppKit")

from wintranslate import selection_macos  # noqa: E402


class FakePasteboard:
    """Starts holding ``previous``. ``copy`` simulates the target app answering
    Cmd+C: it clears the board at once and writes ``text`` only after
    ``reads_before_data`` further reads, like ``clearContents`` followed by a
    slow ``writeObjects:``."""

    def __init__(self, previous, text=None, reads_before_data=0, ignored_copies=0):
        self._text = previous
        self._pending = text
        self._reads_left = reads_before_data
        self._ignored_left = ignored_copies
        self._count = 1
        self.copies = 0
        self.writes = []

    def copy(self):
        self.copies += 1
        if self._pending is None:
            return  # the app ignored Cmd+C
        if self._ignored_left:
            self._ignored_left -= 1
            return  # this one arrived while the app was not listening
        self._count += 1
        self._text = None

    def changeCount(self):
        return self._count

    def stringForType_(self, _type):
        if self._text is None and self._pending is not None and self._count > 1:
            if self._reads_left == 0:
                self._text, self._pending = self._pending, None
            else:
                self._reads_left -= 1
        return self._text

    def clearContents(self):
        self._count += 1
        self._text = None

    def setString_forType_(self, text, _type):
        self._text = text
        self.writes.append(text)
        return True


@pytest.fixture
def board(monkeypatch):
    def install(fake):
        monkeypatch.setattr(selection_macos, "AXIsProcessTrusted", lambda: True)
        # A stand-in for the class: PyObjC does not let a selector be patched.
        monkeypatch.setattr(
            selection_macos, "NSPasteboard", SimpleNamespace(generalPasteboard=lambda: fake)
        )
        monkeypatch.setattr(selection_macos, "_post_copy", fake.copy)
        monkeypatch.setattr(selection_macos, "_COPY_POLL_INTERVAL", 0.001)
        monkeypatch.setattr(selection_macos, "_COPY_RETRY_SECONDS", 0.02)
        return fake

    return install


class TestCaptureSelection:
    def test_returns_the_copied_text_and_restores_the_old_one(self, board):
        fake = board(FakePasteboard(previous="old", text="selected"))
        assert selection_macos.capture_selection() == "selected"
        assert fake.writes == ["old"]

    def test_waits_for_data_written_after_the_board_was_cleared(self, board):
        # changeCount moves on clearContents; the text arrives several polls
        # later. Reading once at the first change would get None.
        fake = board(FakePasteboard(previous="old", text="selected", reads_before_data=5))
        assert selection_macos.capture_selection() == "selected"
        assert fake.writes == ["old"]

    def test_empty_when_the_app_ignores_the_copy(self, board, monkeypatch):
        monkeypatch.setattr(selection_macos, "_COPY_TIMEOUT_SECONDS", 0.05)
        fake = board(FakePasteboard(previous="old", text=None))
        assert selection_macos.capture_selection() == ""
        assert fake.writes == [], "the clipboard must be left alone"

    def test_an_empty_clipboard_stays_empty(self, board):
        fake = board(FakePasteboard(previous=None, text="selected"))
        assert selection_macos.capture_selection() == "selected"
        assert fake.writes == []
        assert fake.stringForType_(None) is None

    def test_refuses_without_accessibility_permission(self, monkeypatch):
        monkeypatch.setattr(selection_macos, "AXIsProcessTrusted", lambda: False)
        with pytest.raises(selection_macos.SelectionError, match="Accessibility"):
            selection_macos.capture_selection()

    def test_sends_cmd_c_again_when_the_first_is_not_answered(self, board):
        fake = board(FakePasteboard(previous="old", text="selected", ignored_copies=1))
        assert selection_macos.capture_selection() == "selected"
        assert fake.copies == 2
        assert fake.writes == ["old"]

    def test_gives_up_after_the_last_attempt(self, board, monkeypatch):
        monkeypatch.setattr(selection_macos, "_COPY_TIMEOUT_SECONDS", 0.2)
        fake = board(FakePasteboard(previous="old", text=None))
        assert selection_macos.capture_selection() == ""
        assert fake.copies == selection_macos._COPY_ATTEMPTS

    def test_logs_an_unanswered_copy(self, board, monkeypatch, caplog):
        monkeypatch.setattr(selection_macos, "_COPY_TIMEOUT_SECONDS", 0.05)
        board(FakePasteboard(previous="old", text=None))
        with caplog.at_level("WARNING"):
            assert selection_macos.capture_selection() == ""
        assert "no answer" in caplog.text and "attempts=" in caplog.text
