# PyInstaller spec for the self-contained app: win-translate.app on macOS, a
# win-translate folder with win-translate.exe on Windows. Run it through
# scripts/package.py, which makes the icon first and passes its path in
# WIN_TRANSLATE_ICON.
#
# onedir, not onefile: a onefile app unpacks itself into a temporary _MEI
# folder on every launch, so it starts slower and leaves that folder behind
# when it crashes.

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is defined by PyInstaller
sys.path.insert(0, str(ROOT))

from wintranslate import __version__  # noqa: E402

APP_NAME = "win-translate"
BUNDLE_ID = "io.github.thanhnvse.win-translate"
ICON = os.environ.get("WIN_TRANSLATE_ICON")

# Unused standard-library weight.
EXCLUDES = ["tkinter", "unittest", "pydoc", "test"]
if sys.platform == "darwin":
    # QtTextToSpeech depends on QtMultimedia, whose hook brings in FFmpeg:
    # +21.9 MB on a minimal build, 17.3 MB of it FFmpeg. The darwin engine
    # speaks through AVSpeechSynthesizer, so the Python module goes; reading
    # aloud then added 2.0 MB to this app and 0.8-1.4 MB to the DMG, and the
    # frozen app still read Vietnamese with Linh (--speak-test).
    # The Qt framework itself stays; QtTextToSpeech links it.
    # Not on Windows: the winrt engine plays through Qt Multimedia's
    # QAudioSink, so there only FFmpeg is dropped, below.
    EXCLUDES += ["PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"]

#: Bundled by the hooks, used by nothing here. FFmpeg is Qt Multimedia's
#: backend for media files; Qt documents the Windows Media Foundation plugin,
#: which stays, as the alternative backend. That winrt still speaks with
#: FFmpeg gone has not been checked on a real Windows machine; run
#: `win-translate.exe --speak-test report.txt vi` there. The mock engine is
#: Qt's fake test voice, which Qt says not to deploy. --self-check fails if
#: any of these come back.
UNUSED_BINARIES = (
    "avcodec", "avformat", "avutil", "swresample", "swscale",
    "ffmpegmediaplugin", "qtexttospeech_mock",
)  # fmt: skip

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    # flags.py and theme.py look for <package>/../assets; in the frozen app the
    # package's parent is the bundle's root, so the folder goes there.
    datas=[(str(ROOT / "assets"), "assets")],
    excludes=EXCLUDES,
)
a.binaries = [
    entry
    for entry in a.binaries
    if not any(name in Path(entry[0]).name.lower() for name in UNUSED_BINARIES)
]
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=ICON,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier=BUNDLE_ID,
        version=__version__,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            # Menu bar only: no Dock icon and no Cmd+Tab entry, from launch on.
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            # The PySide6 pinned in packaging/constraints.txt (6.11) is built
            # for macOS 13 and later.
            "LSMinimumSystemVersion": "13.0",
        },
    )
