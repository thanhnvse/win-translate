"""The icon: a W with a small "tr" tucked under its right arm.

The "t" rises higher than win-voice-over's "vo", so at that app's overlap it
cut into the W. The layout backs off until there is a gap, and these check the
gap and that the pair still sits inside the square, in whatever font the
platform supplies.
"""

import pytest


@pytest.fixture
def placed(qapp):
    from PySide6.QtGui import QFont

    from wintranslate import app

    side = float(app._ICON_GRID)
    letter = app._glyphs(app._ICON_LETTER, side * app._ICON_LETTER_SIZE, QFont.Black)
    suffix = app._glyphs(app._ICON_SUFFIX, side * app._ICON_SUFFIX_SIZE, QFont.Bold)
    return app._tuck(letter, suffix, 0.0, side)


class TestIconLayout:
    def test_the_suffix_does_not_touch_the_letter(self, placed):
        letter, suffix = placed
        assert not letter.intersects(suffix)

    def test_a_gap_shows_between_them(self, placed):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainterPathStroker

        from wintranslate import app

        letter, suffix = placed
        # Slightly under the configured gap, to stay clear of curve rounding.
        margin = QPainterPathStroker()
        margin.setWidth(app._ICON_GAP * 2 * 0.9)
        margin.setJoinStyle(Qt.RoundJoin)
        assert not letter.intersects(margin.createStroke(suffix).united(suffix))

    def test_the_suffix_sits_at_the_letters_lower_right(self, placed):
        letter, suffix = placed
        a, b = letter.boundingRect(), suffix.boundingRect()
        assert b.left() > a.center().x()
        assert b.bottom() > a.bottom(), "the suffix hangs below the W's foot"

    def test_the_pair_stays_inside_the_square(self, placed):
        from PySide6.QtCore import QRectF

        from wintranslate import app

        square = QRectF(0, 0, app._ICON_GRID, app._ICON_GRID)
        for path in placed:
            assert square.contains(path.boundingRect())

    def test_draws_at_the_size_asked_for(self, qapp):
        from wintranslate.app import draw_icon

        for size in (16, 64, 410):
            pixmap = draw_icon(size)
            assert (pixmap.width(), pixmap.height()) == (size, size)
            assert not pixmap.toImage().isNull()
