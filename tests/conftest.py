import os
import sys

# Must be set before PySide6 creates a QApplication, so the GUI tests run
# without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Qt's test engine: it reads nothing aloud and works under offscreen, where
# the macOS engine never starts speaking. Its five locales (en_GB, en_US,
# fi_FI, nb_NO, nn_NO) include no Vietnamese.
os.environ.setdefault("WIN_TRANSLATE_TTS_ENGINE", "mock")
if sys.platform == "win32":
    # The offscreen platform on Windows reads fonts only from this folder, and
    # the PySide6 wheel ships none, so every glyph came out as a box and the
    # icon layout tests failed. Point it at the system's fonts.
    os.environ.setdefault(
        "QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    )

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
