"""Popup sizing.

These exist because the height logic broke twice while it was being written:
once because the layouts' cached size hints were never invalidated, and once
because a fixed height set for one translation clamped the measurements taken
for the next one. Both bugs looked like "the popup is always the same height".
"""

import statistics

import pytest

from wintranslate.popup import _position_near_cursor, _preview

WIDTH = 460
MAX_HEIGHT = 420

SHORT = "Xin chao"
ONE_LINE = "Xin chao the gioi, hom nay ban the nao?"
PARAGRAPH = "Con meo ngoi tren tam tham. " * 8
VERY_LONG = "Dong rat dai. " * 200


@pytest.fixture
def popup(qapp):
    from wintranslate.popup import TranslationPopup

    return TranslationPopup(width=WIDTH, max_height=MAX_HEIGHT)


def _wrapping_text(popup) -> str:
    """A sentence just wider than one line in the popup's own font.

    A fixed string cannot do this: ONE_LINE wraps with Windows' fonts but fits on
    one line with macOS's, which made it no taller than SHORT there.
    """
    from PySide6.QtGui import QFontMetrics

    metrics = QFontMetrics(popup._translation.font())
    words = ONE_LINE.split()
    text = ""
    while metrics.horizontalAdvance(text) <= popup._content_width * 1.3:
        text = f"{text} {words[len(text.split()) % len(words)]}".strip()
    return text


def height_for(popup, text: str) -> int:
    popup.show_result("source", text, "en")
    return popup.height()


class TestPopupSizing:
    def test_width_is_fixed(self, popup):
        for text in (SHORT, VERY_LONG):
            popup.show_result("source", text, "en")
            assert popup.width() == WIDTH

    def test_taller_text_makes_a_taller_popup(self, popup):
        short = height_for(popup, SHORT)
        two_lines = height_for(popup, _wrapping_text(popup))
        paragraph = height_for(popup, PARAGRAPH)
        assert short < two_lines < paragraph

    def test_height_is_capped(self, popup):
        assert height_for(popup, VERY_LONG) == MAX_HEIGHT

    def test_popup_shrinks_again_after_a_long_translation(self, popup):
        assert height_for(popup, VERY_LONG) == MAX_HEIGHT
        assert height_for(popup, SHORT) < MAX_HEIGHT

    def test_height_depends_only_on_the_current_text(self, popup):
        """Same text, same height, whatever came before it."""
        fresh = height_for(popup, PARAGRAPH)
        height_for(popup, VERY_LONG)
        after_long = height_for(popup, PARAGRAPH)
        height_for(popup, SHORT)
        after_short = height_for(popup, PARAGRAPH)
        assert fresh == after_long == after_short

    def test_pending_and_error_states_size_themselves(self, popup):
        height_for(popup, VERY_LONG)
        popup.show_pending("Hello")
        assert popup.height() < MAX_HEIGHT
        popup.show_error("Nothing was selected.")
        assert popup.height() < MAX_HEIGHT

    def test_a_huge_source_selection_does_not_inflate_the_popup(self, popup):
        popup.show_result("x" * 4000, SHORT, "en")
        assert popup.height() < MAX_HEIGHT


class TestPopupContent:
    def test_shows_the_detected_language_in_the_heading(self, popup):
        popup.show_result("Hello", "Xin chào", "en")
        assert "EN" in popup._heading.text()

    def test_detected_language_can_be_suppressed(self, popup):
        popup.show_result("Hello", "Xin chào", "en", show_detected=False)
        assert "EN" not in popup._heading.text()

    def test_missing_detected_language_still_renders(self, popup):
        popup.show_result("Hello", "Xin chào", None)
        assert popup._heading.text()

    def test_copy_is_disabled_until_there_is_a_result(self, popup):
        popup.show_pending("Hello")
        assert not popup._copy_button.isEnabled()
        popup.show_result("Hello", "Xin chào", "en")
        assert popup._copy_button.isEnabled()
        popup.show_error("failed")
        assert not popup._copy_button.isEnabled()

    def test_copy_puts_the_translation_on_the_clipboard(self, popup, qapp):
        popup.show_result("Hello", "Xin chào", "en")
        popup._copy_translation()
        assert qapp.clipboard().text() == "Xin chào"


class TestPopupAppearance:
    """Pixel checks.

    The sizing tests all passed while the translation was invisible: near-white
    text on the scroll area's default white viewport. Geometry being right says
    nothing about the thing being readable, so these sample actual pixels.
    """

    def _background_lightness(self, popup) -> float:
        """Median lightness over the translation area.

        The median rather than the maximum, because the translation text is
        deliberately near-white: sampling a band that crosses glyphs will always
        find light pixels. Background dominates the area, so a white viewport
        moves the median while ordinary text does not.
        """
        image = popup.grab().toImage()
        rect = popup._scroll.geometry()
        top = popup._scroll.mapTo(popup, rect.topLeft()).y()
        values = [
            image.pixelColor(x, y).lightness()
            # Inset so the card border and the scrollbar gutter stay out of it.
            for x in range(20, popup.width() - 30, 3)
            for y in range(top + 2, top + rect.height() - 2, 3)
        ]
        assert values, "expected to sample some pixels"
        return statistics.median(values)

    def test_translation_sits_on_the_dark_card_not_a_white_block(self, popup):
        popup.show_result("buffer", "đệm", "en")
        # The card is #1e1f24 (lightness ~33). The regression this guards against
        # painted QPalette.Base white behind the text.
        assert self._background_lightness(popup) < 120

    def test_the_same_holds_for_a_long_translation(self, popup):
        popup.show_result("src", "Dong rat dai. " * 200, "en")
        assert self._background_lightness(popup) < 120

    def test_the_same_holds_for_the_error_state(self, popup):
        popup.show_error("Nothing was selected.")
        assert self._background_lightness(popup) < 120

    def test_scroll_viewport_does_not_fill_its_background(self, popup):
        assert not popup._scroll.viewport().autoFillBackground()


class TestClosing:
    def test_escape_hides_the_popup(self, popup, qapp):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        popup.show_result("Hello", "Xin chào", "en")
        assert popup.isVisible()
        popup.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        )
        assert not popup.isVisible()

    def test_there_is_a_close_button_that_hides_the_popup(self, popup):
        from PySide6.QtWidgets import QPushButton

        close = popup.findChild(QPushButton, "close")
        assert close is not None, "the popup needs a visible way to dismiss it"
        popup.show_result("Hello", "Xin chào", "en")
        assert popup.isVisible()
        close.click()
        assert not popup.isVisible()

    def test_hint_returns_after_a_copy(self, popup, qapp):
        from PySide6.QtCore import QTimer
        from wintranslate.popup import _HINT_TEXT

        popup.show_result("Hello", "Xin chào", "en")
        popup._copy_translation()
        assert popup._hint.text() != _HINT_TEXT

        # Let the revert timer fire.
        loop_done = []
        QTimer.singleShot(1800, lambda: loop_done.append(True))
        while not loop_done:
            qapp.processEvents()
        assert popup._hint.text() == _HINT_TEXT


class TestPreview:
    def test_collapses_whitespace_to_one_line(self):
        assert _preview("a\n\n  b\tc  ") == "a b c"

    def test_caps_length_with_an_ellipsis(self):
        result = _preview("x" * 500, limit=120)
        assert len(result) == 121 and result.endswith("…")

    def test_leaves_short_text_alone(self):
        assert _preview("short") == "short"


class TestPositioning:
    def test_stays_within_the_screen(self, qapp):
        from PySide6.QtGui import QGuiApplication

        area = QGuiApplication.primaryScreen().availableGeometry()
        point = _position_near_cursor(WIDTH, MAX_HEIGHT)
        assert area.left() <= point.x()
        assert point.x() + WIDTH <= area.right() + 1
        assert area.top() <= point.y()
        assert point.y() + MAX_HEIGHT <= area.bottom() + 1


class TestDismissal:
    def test_hides_when_another_window_takes_activation(self, popup, qapp):
        # The click-elsewhere case. focusOutEvent never reaches the popup itself
        # because a child holds keyboard focus, so activation is what counts.
        from PySide6.QtWidgets import QWidget

        popup.show_result("source", "text", "en")
        qapp.processEvents()
        assert popup.isVisible()

        other = QWidget()
        other.show()
        other.activateWindow()
        qapp.processEvents()
        try:
            assert not popup.isVisible()
        finally:
            other.close()

    def test_escape_hides(self, popup, qapp):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        popup.show_result("source", "text", "en")
        qapp.sendEvent(popup, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not popup.isVisible()
