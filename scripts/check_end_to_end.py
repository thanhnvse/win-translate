"""Manual end-to-end check: hotkey -> capture -> translate -> popup.

Assumes win-translate is already running (``python -m wintranslate``). It opens
its own fixture window with English text selected, fires the configured hotkey,
waits for the translation, and saves a screenshot so the result can be inspected.

    .venv\\Scripts\\python.exe scripts\\check_end_to_end.py

Like check_selection.py, it never touches an application it did not start.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_selection import open_fixture_window  # noqa: E402
from wintranslate.config import Config  # noqa: E402
from wintranslate.hotkey import (  # noqa: E402
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    parse_hotkey,
)
from wintranslate.selection import _key_event, _send  # noqa: E402

FIXTURE_TEXT = (
    "The deployment failed because the database connection pool was exhausted."
)

_MODIFIER_VK = {
    MOD_CONTROL: 0x11,  # VK_CONTROL
    MOD_ALT: 0x12,      # VK_MENU
    MOD_SHIFT: 0x10,    # VK_SHIFT
    MOD_WIN: 0x5B,      # VK_LWIN
}

_SCREENSHOT_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)
"""


def send_hotkey(spec: str) -> None:
    modifiers, virtual_key = parse_hotkey(spec)
    held = [vk for flag, vk in _MODIFIER_VK.items() if modifiers & flag]

    events = [_key_event(vk, key_up=False) for vk in held]
    events += [_key_event(virtual_key, key_up=False),
               _key_event(virtual_key, key_up=True)]
    events += [_key_event(vk, key_up=True) for vk in reversed(held)]
    _send(events)


def screenshot(path: Path) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         _SCREENSHOT_PS.format(path=str(path).replace("\\", "\\\\"))],
        check=True,
        capture_output=True,
    )


def main() -> int:
    config = Config.load()
    tmp_dir = Path(__file__).resolve().parent.parent / ".pytest_cache" / "e2e"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    shot = tmp_dir / "popup.png"

    print(f"hotkey: {config.hotkey}")
    print(f"text  : {FIXTURE_TEXT}")

    window = open_fixture_window(FIXTURE_TEXT, tmp_dir)
    try:
        time.sleep(0.5)
        send_hotkey(config.hotkey)
        print("hotkey sent, waiting for the translation...")
        time.sleep(4)
        screenshot(shot)
        print(f"screenshot: {shot}")
    finally:
        window.kill()
        window.wait(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
