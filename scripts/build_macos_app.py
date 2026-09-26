"""Build win-translate.app for macOS and install it.

The bundle does not contain Python or the code. It holds a small launcher
(packaging/macos/launcher.c) that runs ``python -m wintranslate`` from *this*
checkout's ``.venv.nosync``, which means:

* editing the code, or ``git pull``, takes effect on the next launch — no
  rebuild;
* moving the checkout, or renaming the venv, needs a rebuild;
* Accessibility is granted to "win-translate" itself, not to Terminal. A
  rebuild produces a new binary, and macOS may then ask for it again.

Run it from the project root:

    .venv.nosync/bin/python scripts/build_macos_app.py

``--dest`` picks another folder than /Applications, e.g. ``~/Applications``.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

APP_NAME = "win-translate"
BUNDLE_ID = "io.github.thanhnvse.win-translate"
LOG_NAME = "win-translate.log"
LAUNCHER_SOURCE = ROOT / "packaging" / "macos" / "launcher.c"
#: Not resolved: Python finds its venv from the path it was started as.
PYTHON = ROOT / ".venv.nosync" / "bin" / "python"

#: An .iconset holds each of these at 1x and 2x.
ICON_SIZES = (16, 32, 128, 256, 512)
#: Apple's icon grid leaves a margin around the artwork; a full-bleed square
#: looks oversized next to every other icon in the Dock and Launchpad.
ICON_ARTWORK_SCALE = 0.8


class BuildError(Exception):
    pass


def c_string(value: str) -> str:
    """Quote ``value`` as a C string literal for a ``-D`` definition."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run(*command: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(
            f"{' '.join(command)} failed ({result.returncode}):\n"
            f"{result.stdout}{result.stderr}"
        )


def compile_launcher(output: Path) -> None:
    run(
        "clang", "-O2", "-Wall", "-Wextra", "-Werror",
        f"-DREPO_DIR={c_string(str(ROOT))}",
        f"-DPYTHON={c_string(str(PYTHON))}",
        f"-DLOG_NAME={c_string(LOG_NAME)}",
        "-o", str(output), str(LAUNCHER_SOURCE),
    )  # fmt: skip


def build_icon(output: Path, workdir: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - QPixmap needs it
    from wintranslate.app import draw_icon

    iconset = workdir / "AppIcon.iconset"
    iconset.mkdir()
    for size in ICON_SIZES:
        for scale in (1, 2):
            pixels = size * scale
            artwork = draw_icon(round(pixels * ICON_ARTWORK_SCALE))
            canvas = QPixmap(pixels, pixels)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            offset = (pixels - artwork.width()) // 2
            painter.drawPixmap(offset, offset, artwork)
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            path = iconset / f"icon_{size}x{size}{suffix}.png"
            if not canvas.save(str(path), "PNG"):
                raise BuildError(f"Could not write {path}")

    run("iconutil", "--convert", "icns", str(iconset), "--output", str(output))


def info_plist() -> dict:
    from wintranslate import __version__

    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        # Menu bar only: no Dock icon, no Cmd+Tab entry, for the launcher too.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    }


def build_bundle(app: Path, workdir: Path) -> None:
    macos_dir = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    compile_launcher(macos_dir / APP_NAME)
    build_icon(resources / "AppIcon.icns", workdir)
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump(info_plist(), handle)

    # Ad-hoc: no Apple developer identity needed. It binds Info.plist and the
    # icon to the binary, which is what macOS keys the permission on.
    run("codesign", "--force", "--sign", "-", "--identifier", BUNDLE_ID, str(app))
    run("codesign", "--verify", "--strict", str(app))


def is_running(app: Path) -> bool:
    executable = str(app / "Contents" / "MacOS" / APP_NAME)
    return subprocess.run(["pgrep", "-f", executable], capture_output=True).returncode == 0


def install(built: Path, target: Path) -> None:
    if target.exists():
        existing = target / "Contents" / "Info.plist"
        try:
            with open(existing, "rb") as handle:
                bundle_id = plistlib.load(handle).get("CFBundleIdentifier")
        except (OSError, plistlib.InvalidFileException) as exc:
            raise BuildError(f"{target} exists and is not a readable app bundle: {exc}") from exc
        if bundle_id != BUNDLE_ID:
            raise BuildError(f"{target} belongs to {bundle_id!r}; not replacing it.")
        if is_running(target):
            raise BuildError(f"{APP_NAME} is running. Quit it from the menu bar W first.")
        shutil.rmtree(target)
    # ditto, not copytree: it is the macOS tool for copying bundles intact.
    run("ditto", str(built), str(target))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=Path("/Applications"))
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("This builds a macOS app; run it on a Mac.", file=sys.stderr)
        return 1
    if not os.access(PYTHON, os.X_OK):
        print(f"No virtualenv at {PYTHON.parent.parent} — follow Install in README.md.",
              file=sys.stderr)  # fmt: skip
        return 1

    dest = args.dest.expanduser()
    target = dest / f"{APP_NAME}.app"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            built = Path(tmp) / f"{APP_NAME}.app"
            build_bundle(built, Path(tmp))
            install(built, target)
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Installed {target}")
    print(f"It runs {PYTHON} -m wintranslate in {ROOT}; logs go to ~/Library/Logs/{LOG_NAME}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
