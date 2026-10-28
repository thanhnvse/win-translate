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

    def test_markup_in_the_selection_is_shown_literally(self, popup):
        from PySide6.QtCore import Qt

        popup.show_result("<b>Hello</b>", "<i>Xin chào</i>", "en")
        assert popup._source.textFormat() == Qt.PlainText
        assert popup._translation.textFormat() == Qt.PlainText
        assert popup._translation.text() == "<i>Xin chào</i>"

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
    nothing about the thing being readable, so these sample actual pixels -- and
    they run for every theme, because a light theme is exactly where a palette
    inherited from a dark one goes wrong.
    """

    def _background_lightness(self, popup) -> float:
        """Median lightness over the translation area.

        The median rather than the extreme, because the translation text is one
        colour and the card another: sampling a band that crosses glyphs always
        finds both. Background dominates the area, so the median tracks the card.
        """
        image = popup.grab().toImage()
        rect = popup._scroll.geometry()
        top = popup._scroll.mapTo(popup, rect.topLeft()).y()
        left = popup._scroll.mapTo(popup, rect.topLeft()).x()
        values = [
            image.pixelColor(x, y).lightness()
            for x in range(left + 2, left + rect.width() - 10, 3)
            for y in range(top + 2, top + rect.height() - 2, 3)
        ]
        assert values, "expected to sample some pixels"
        return statistics.median(values)

    @pytest.mark.parametrize("key", ["light", "dark", "colorful"])
    def test_the_translation_contrasts_with_its_card_in_every_theme(self, popup, key):
        from PySide6.QtGui import QColor

        from wintranslate import theme as theming

        popup.apply_appearance(WIDTH, MAX_HEIGHT, key)
        popup.show_result("buffer", "dem", "en")
        background = self._background_lightness(popup)
        text = QColor(theming.get(key).title).lightness()
        assert abs(text - background) > 60, (
            f"{key}: text lightness {text} against a card measured at {background}"
        )

    @pytest.mark.parametrize("key", ["light", "dark", "colorful"])
    def test_the_same_holds_for_a_long_translation(self, popup, key):
        from PySide6.QtGui import QColor

        from wintranslate import theme as theming

        popup.apply_appearance(WIDTH, MAX_HEIGHT, key)
        popup.show_result("src", "Dong rat dai. " * 200, "en")
        text = QColor(theming.get(key).title).lightness()
        assert abs(text - self._background_lightness(popup)) > 60

    def test_the_error_state_is_not_the_card_colour(self, popup):
        from PySide6.QtGui import QColor

        from wintranslate import theme as theming

        popup.show_error("Google Translate returned HTTP 429.")
        error = QColor(theming.get("light").error).lightness()
        assert abs(error - self._background_lightness(popup)) > 40

    def test_scroll_viewport_does_not_fill_its_background(self, popup):
        assert not popup._scroll.viewport().autoFillBackground()



class TestGradientThemes:
    """A gradient colour and selectable text cannot coexist in a QLabel:
    TextSelectableByMouse renders through a QTextDocument, whose character
    format takes a solid colour, so the gradient is silently dropped."""

    def test_a_gradient_theme_turns_selection_off_to_keep_its_colour(self, popup):
        from PySide6.QtCore import Qt

        for key in ("colorful", "neon"):
            popup.apply_appearance(WIDTH, MAX_HEIGHT, key)
            assert popup._translation.textInteractionFlags() == Qt.NoTextInteraction, key

    def test_a_plain_theme_keeps_its_selectable_text(self, popup):
        from PySide6.QtCore import Qt

        for key in ("light", "dark"):
            popup.apply_appearance(WIDTH, MAX_HEIGHT, key)
            assert popup._translation.textInteractionFlags() == Qt.TextSelectableByMouse, key

    def test_the_gradient_actually_reaches_the_glyphs(self, popup, qapp):
        """The bug this guards shipped once: the stylesheet carried a gradient,
        every structural check passed, and the text still rendered flat black.

        Compared image against image rather than by sampling colours. Several
        hand-written pixel metrics were tried here first and each one called a
        working render broken -- hue counting cannot tell a gradient from the
        unstable hues of anti-aliased near-black text. Two renders that differ
        only by whether selection is on cannot both be flat black.
        """
        from PySide6.QtCore import Qt

        popup.apply_appearance(WIDTH, MAX_HEIGHT, "neon")
        popup.show_result("src", "the connection pool was exhausted", "vi", target="en")
        qapp.processEvents()
        with_gradient = popup._translation.grab().toImage()

        # Selection forces rendering through a QTextDocument, which drops the
        # gradient; this is what the broken version looked like.
        popup._translation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        qapp.processEvents()
        without = popup._translation.grab().toImage()

        assert with_gradient != without, (
            "the gradient theme renders the same as the solid fallback, "
            "so the gradient is not reaching the text"
        )

    def test_copy_still_takes_the_whole_translation(self, popup, qapp):
        """Selection is what was given up, not copying."""
        popup.apply_appearance(WIDTH, MAX_HEIGHT, "colorful")
        popup.show_result("src", "Xin chào", "en")
        popup._copy_translation()
        assert qapp.clipboard().text() == "Xin chào"


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

        close = popup.findChild(QPushButton, "secondary")
        assert close is not None, "the popup needs a visible way to dismiss it"
        popup.show_result("Hello", "Xin chào", "en")
        assert popup.isVisible()
        close.click()
        assert not popup.isVisible()

    def test_the_copy_button_confirms_and_then_resets(self, popup, qapp):
        """The button is the only feedback now that the hint line is gone."""
        from PySide6.QtCore import QTimer

        popup.show_result("Hello", "Xin chao", "en")
        popup._copy_translation()
        assert popup._copy_button.text() == "Copied"

        done = []
        QTimer.singleShot(1800, lambda: done.append(True))
        while not done:
            qapp.processEvents()
        assert popup._copy_button.text() == "Copy"


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


class TestWindowShadow:
    def test_asks_the_system_for_no_shadow_of_its_own(self, popup):
        # The card draws its own shadow in a transparent margin. A system
        # shadow is traced from every pixel that is not fully transparent, so
        # it outlined that whole margin in a dark ring on macOS, on every theme.
        from PySide6.QtCore import Qt

        assert popup.windowFlags() & Qt.NoDropShadowWindowHint
        assert popup.testAttribute(Qt.WA_TranslucentBackground)

    def test_keeps_the_shadow_hint_after_a_theme_change(self, popup):
        from PySide6.QtCore import Qt

        popup.apply_appearance(WIDTH, MAX_HEIGHT, "neon")
        assert popup.windowFlags() & Qt.NoDropShadowWindowHint
