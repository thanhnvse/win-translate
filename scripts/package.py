"""Build the self-contained download for this platform.

The result needs nothing on the target machine -- no Python, git or compiler:

* macOS: ``dist.nosync/win-translate-<version>-macos-<arch>.dmg``, holding
  win-translate.app and a shortcut to Applications to drag it onto.
* Windows: ``dist.nosync/win-translate-<version>-windows-x64-setup.exe``, an
  Inno Setup installer.

Steps: draw the icon, freeze the app with PyInstaller (packaging/
win-translate.spec), run the frozen app's ``--self-check`` and stop if anything
is missing, then wrap it. The release workflow runs this on each platform;
it works the same locally:

    python -m pip install -r requirements.txt -r requirements-build.txt -c packaging/constraints.txt
    python scripts/package.py

The freezing happens in the system's temporary folder, not in the checkout:
in an iCloud-synced ~/Documents the File Provider tags folders with Finder
information, and codesign then refuses to seal the bundle ("resource fork,
Finder information, or similar detritus not allowed") -- PyInstaller only
warns, and the app would ship unsigned. The output folder is named *.nosync,
a name iCloud leaves alone.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

APP_NAME = "win-translate"
SPEC = ROOT / "packaging" / "win-translate.spec"
ISS = ROOT / "packaging" / "windows" / "win-translate.iss"
WORK = Path(tempfile.gettempdir()) / "win-translate-package"
DIST = ROOT / "dist.nosync"
#: Inno Setup's compiler, where its installer puts it, when it is not on PATH
#: (GitHub's Windows image puts it there); override with ISCC.
DEFAULT_ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
#: Long enough for a slow CI machine. A windowed .exe that crashes shows a modal
#: traceback dialog instead of exiting, which would otherwise hang the build.
SELF_CHECK_TIMEOUT_SECONDS = 180
#: The sizes a Windows .ico carries; Explorer picks the nearest.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


class PackageError(Exception):
    pass


def run(*command: str, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, env=env)
    if result.returncode != 0:
        raise PackageError(f"{command[0]} failed with exit status {result.returncode}")


def version() -> str:
    from wintranslate import __version__

    return __version__


def arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64" if sys.platform == "win32" else "x86_64"}.get(
        machine, machine
    )


def make_icon(workdir: Path) -> Path:
    if sys.platform == "darwin":
        # The .icns the developer build already makes, drawn under Cocoa so it
        # matches the menu-bar icon.
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_macos_app import build_icon

        icns = workdir / "AppIcon.icns"
        build_icon(icns, workdir)
        return icns
    return _make_ico(workdir / "win-translate.ico")


def _make_ico(path: Path) -> Path:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from wintranslate.app import draw_icon

    app = QApplication.instance() or QApplication([])  # noqa: F841 - QPixmap needs it
    largest = max(ICO_SIZES)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    draw_icon(largest).save(buffer, "PNG")
    master = Image.open(_bytes_io(bytes(buffer.data())))
    # Pillow scales the 256 px drawing down to every size listed.
    master.save(path, format="ICO", sizes=[(size, size) for size in ICO_SIZES])
    return path


def _bytes_io(data: bytes):
    import io

    return io.BytesIO(data)


def freeze(icon: Path) -> Path:
    env = dict(os.environ, WIN_TRANSLATE_ICON=str(icon))
    run(
        sys.executable, "-m", "PyInstaller", str(SPEC),
        "--noconfirm", "--clean",
        "--workpath", str(WORK / "pyinstaller"),
        "--distpath", str(WORK / "frozen"),
        env=env,
    )  # fmt: skip
    if sys.platform == "darwin":
        return WORK / "frozen" / f"{APP_NAME}.app"
    return WORK / "frozen" / APP_NAME


def verify_signature(app: Path) -> None:
    """Stop here if the bundle is not properly sealed.

    PyInstaller signs the bundle ad hoc, but a failure there is only a warning.
    A downloaded app with a broken seal is reported by macOS as damaged.
    """
    run("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app))


def self_check(frozen: Path) -> None:
    if sys.platform == "darwin":
        executable = frozen / "Contents" / "MacOS" / APP_NAME
    else:
        executable = frozen / f"{APP_NAME}.exe"
    report = WORK / "self-check.txt"
    report.unlink(missing_ok=True)
    print("+", executable, "--self-check", report, flush=True)
    try:
        status = subprocess.run(
            [str(executable), "--self-check", str(report)],
            timeout=SELF_CHECK_TIMEOUT_SECONDS,
        ).returncode
    except subprocess.TimeoutExpired as exc:
        raise PackageError(
            f"the frozen app's self-check did not finish in {SELF_CHECK_TIMEOUT_SECONDS} s; "
            "a crash dialog may be waiting for a click"
        ) from exc
    findings = report.read_text(encoding="utf-8") if report.exists() else "(no report written)\n"
    print(findings, end="")
    if status != 0:
        raise PackageError(f"the frozen app failed its self-check (exit status {status})")


def make_dmg(app: Path) -> Path:
    out = DIST / f"{APP_NAME}-{version()}-macos-{arch()}.dmg"
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / APP_NAME
        staging.mkdir()
        # ditto keeps the bundle's symlinks and code signature intact.
        run("ditto", str(app), str(staging / app.name))
        (staging / "Applications").symlink_to("/Applications")
        run(
            "hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging),
            "-ov", "-format", "UDZO", str(out),
        )  # fmt: skip
    return out


def make_installer(folder: Path) -> Path:
    found = os.environ.get("ISCC") or shutil.which("iscc") or str(DEFAULT_ISCC)
    iscc = Path(found)
    if not iscc.is_file():
        raise PackageError(f"Inno Setup's compiler is not at {iscc}; set ISCC to its path")
    name = f"{APP_NAME}-{version()}-windows-{arch()}-setup"
    run(
        str(iscc),
        f"/DAppVersion={version()}",
        f"/DSourceDir={folder}",
        f"/DIconFile={WORK / 'icon' / 'win-translate.ico'}",
        f"/O{DIST}",
        f"/F{name}",
        str(ISS),
    )  # fmt: skip
    return DIST / f"{name}.exe"


def main() -> int:
    if sys.platform not in ("darwin", "win32"):
        print("Packages are built on macOS or Windows.", file=sys.stderr)
        return 1
    try:
        WORK.mkdir(exist_ok=True)
        DIST.mkdir(exist_ok=True)
        icon_dir = WORK / "icon"
        shutil.rmtree(icon_dir, ignore_errors=True)
        icon_dir.mkdir()
        frozen = freeze(make_icon(icon_dir))
        if sys.platform == "darwin":
            verify_signature(frozen)
        self_check(frozen)
        out = make_dmg(frozen) if sys.platform == "darwin" else make_installer(frozen)
    # ImportError: PyInstaller, Pillow or PySide6 missing from this interpreter.
    except (PackageError, ImportError, OSError) as exc:
        print(f"Packaging failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nBuilt {out} ({out.stat().st_size / 1_000_000:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
