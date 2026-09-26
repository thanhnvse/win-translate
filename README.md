# win-translate

A background tray app for Windows and macOS. Select text in any application,
press a hotkey, and a small popup shows the translation next to the cursor:
English in, Vietnamese out — and Vietnamese in, English out.

## Why a hotkey and not a right-click menu

The original idea was a "Translate to Vietnamese" entry in the right-click menu
of any selected text. On Windows that is not possible for a third-party app:

* Shell extensions (`IContextMenu`, and `IExplorerCommand` on Windows 11) apply
  to **files and folders in Explorer**, not to a text selection.
* The menu you get when you right-click selected text is drawn by the
  application itself — Chrome renders its own, Word renders its own. Windows
  exposes no supported way to add an item to it.
* The only technical route is DLL injection or a global hook into other
  processes, which antivirus flags, which breaks against elevated and sandboxed
  apps, and which breaks again on the next Chrome update.

So this uses a global hotkey instead, the same approach DeepL and similar tools
take on Windows. A browser extension is the way to get a real right-click entry
inside Chrome or Edge; that is not part of this repo.

On macOS the original idea *is* achievable, through the Services menu
(`NSServices` in `Info.plist`), but only for a bundled `.app`. The macOS build
here uses the same hotkey as Windows instead, so it runs straight from the
source tree like the Windows one does.

## Install

Requires Python 3.10+.

Windows:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS (also pulls in the PyObjC packages, which are skipped on Windows):

```bash
python3 -m venv .venv.nosync
.venv.nosync/bin/python -m pip install -r requirements.txt
```

The `.nosync` suffix matters when the project sits in a folder iCloud Drive
syncs — `~/Desktop` or `~/Documents` with "Desktop & Documents Folders" on.
iCloud sets the BSD `hidden` flag on every dot-named file and on everything
inside a dot-named directory, within seconds of their creation. Qt's plugin
loader skips hidden files, so a plain `.venv` there starts fine at first and
then fails with *Could not find the Qt platform plugin "cocoa"*. iCloud leaves
anything named `*.nosync` alone — no flag, and no uploading thousands of
package files either. Outside iCloud the suffix is harmless.

## Run on Windows

```bash
.venv\Scripts\pythonw.exe -m wintranslate
```

Use `pythonw.exe` rather than `python.exe` so no console window stays open.
A tray icon appears; the app does nothing else until the hotkey fires.

Default hotkey is **Ctrl+Alt+T**. Select text anywhere, press it, and the popup
appears by the pointer. `Esc`, the `✕`, or clicking elsewhere dismisses it.

The direction is chosen from the text: select English (or anything else) and you
get Vietnamese; select Vietnamese and you get English. One hotkey, both ways.

Or just double-click `start.cmd`.

### Start with Windows

Put a shortcut to `pythonw.exe -m wintranslate` in:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

## Run on macOS

Build an app once, then open it like any other — from Launchpad, Spotlight, or
`/Applications`:

```bash
.venv.nosync/bin/python scripts/build_macos_app.py
```

`win-translate.app` holds no copy of the code: a small launcher
(`packaging/macos/launcher.c`) runs `python -m wintranslate` from this checkout's
`.venv.nosync` and stays its parent. So code changes and `git pull` apply on the
next launch without a rebuild, but moving the checkout needs one. It logs to
`~/Library/Logs/win-translate.log`. `--dest ~/Applications` installs it
elsewhere.

Without the app, run it from a terminal:

```bash
.venv.nosync/bin/python -m wintranslate
```

or double-click `start.command` in Finder. The app lives in the menu bar only —
no Dock icon, no entry in Cmd+Tab.

Default hotkey is **Control+T** (`ctrl+t`). Select text anywhere, press it, and
the popup appears by the pointer. It is free on macOS because browsers use
Command+T for a new tab; what it takes over is Control+T's "transpose letters"
in text fields and in terminal shells. The same hotkey strings as on Windows
work, with `alt`/`option`/`opt` meaning Option and `win`/`cmd`/`command` meaning
Command.

Unlike Windows, macOS does not refuse a combination another app or a system
shortcut already uses: win-translate starts without complaint and the hotkey
simply never fires. If that happens, pick another one in the config.

### Accessibility permission

To copy the selection the app presses Cmd+C for you, and macOS only allows that
for apps granted **Accessibility** permission. On every start without it, the
app asks macOS to show its permission prompt (macOS only does so the first
time) and shows its own dialog explaining where to enable it: System Settings →
Privacy & Security → Accessibility. Restart win-translate afterwards.

The permission is granted to the app that *launched* Python, not to Python
itself: **win-translate** when opened as the app, Terminal or iTerm when run
from a shell or `start.command`, your editor when run from its built-in
terminal. Rebuilding the app produces a new binary, and macOS may ask again. Adding Python
to the list has no effect. Without the permission the hotkey still fires, and
the popup says what is missing.

The hotkey itself needs no permission: it is registered with Carbon
`RegisterEventHotKey`, which only ever reports that one combination.

### Start at login

System Settings → General → Login Items → **+**, and add `win-translate.app`
(or `start.command`).

## Configuration

Written on first run to `%APPDATA%\win-translate\config.json` on Windows and
`~/Library/Application Support/win-translate/config.json` on macOS, and
reachable from the tray menu:

| Key | Default | Notes |
| --- | --- | --- |
| `hotkey` | `ctrl+alt+t` on Windows, `ctrl+t` on macOS | e.g. `ctrl+shift+k`, `ctrl+alt+f2`. Needs at least one modifier. On macOS `alt` is Option and `win`/`cmd` is Command. |
| `target_language` | `vi` | Any Google Translate language code. |
| `alternate_language` | `en` | Where a selection that is *already* Vietnamese goes. Set to `""` to disable the reverse direction. |
| `google_api_key` | `""` | Empty uses the free endpoints. Set it to use Cloud Translation API v2. |
| `popup_width` | `460` | Pixels. |
| `popup_max_height` | `420` | The popup grows with the text up to this, then scrolls. |
| `show_detected_language` | `true` | Shows `ENGLISH → VIETNAMESE` in the popup heading. |

Restart the app after editing.

On Windows, `ctrl+t` and `ctrl+shift+t` are deliberate non-defaults: a global
hotkey outranks an application's own shortcut, so they would take "new tab" and
"reopen closed tab" away from every browser. On macOS browsers use Command for
those, which is why `ctrl+t` is the default there.

## How it works

* **Hotkey** — Win32 `RegisterHotKey` on a dedicated thread with its own message
  loop. Not a keyboard hook: a hook would see every keystroke the user types,
  including passwords, and need elevation to watch elevated apps.
* **Selection** — Windows cannot be asked what another process has selected, so
  the app saves the clipboard, synthesises Ctrl+C into the focused window, waits
  for `GetClipboardSequenceNumber` to move, reads the text, and puts the old
  clipboard back. Modifiers still physically held from the hotkey are released
  first, or the target app would receive Ctrl+Alt+C instead of a copy.
* **On macOS** the same design maps onto Carbon `RegisterEventHotKey` for the
  hotkey (delivered on the Qt main thread rather than a thread of its own),
  `CGEventPost` for Cmd+C, and `NSPasteboard.changeCount` in place of
  `GetClipboardSequenceNumber` — and then polls for the text as well, since the
  pasteboard has no lock and the count moves before the other app has written
  its data. The Cmd+C events come from a private event source with explicit
  flags, so the Control and Option still held from the hotkey do not leak into
  them. Closing the popup hands activation back to the app you were in, which
  Windows does on its own.
* **Translation** — tried against several undocumented Google endpoints in
  order, because one host answering HTTP 429 says nothing about the next.
* **Direction** — cannot be known before the text is seen, and a separate
  detection call would cost a round-trip on every translation. Instead the app
  asks for Vietnamese first and re-translates only when the reply says the input
  was already Vietnamese, so only the reverse direction pays twice.

## Known limitations

* **Technical vocabulary.** Google Translate is weak on it. "Race condition"
  comes back as "tình trạng chủng tộc". If that matters, set an API key and
  consider a different engine.
* **The free endpoints are undocumented** and rate-limited per source IP. On a
  corporate or shared connection some of them answer 429; the provider chain
  exists for exactly that reason, but all of them can be throttled at once.
* **Non-text clipboard contents are lost.** If the clipboard held an image or a
  file list, it is cleared rather than restored. Text is preserved.
* **Elevated applications.** Windows blocks synthesised input from a normal
  process into an elevated one. To translate inside an app running as
  administrator, run win-translate as administrator too.
* **macOS: a taken hotkey fails silently** — see "Run on macOS".
* **macOS: hotkey letters are key positions.** Carbon hotkeys name physical
  keys on an ANSI layout, so on AZERTY `ctrl+alt+a` is the key labelled Q.
* **Apps that do not support Ctrl+C** (some custom controls, PDF viewers in
  protected mode) return nothing, and the popup says so.

## Tests

pytest comes from `requirements-dev.txt`, which running the app does not need.

Windows:

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

macOS:

```bash
.venv.nosync/bin/python -m pip install -r requirements-dev.txt
```

```bash
.venv.nosync/bin/python -m pytest tests -q
```

No network and no display needed — Qt runs under the `offscreen` platform, the
translation tests use a fake HTTP session, and the macOS capture tests use a
fake pasteboard. Each platform skips the other's module: on Windows the macOS
capture tests (they need AppKit), on macOS `tests/test_hotkey.py` (12 Win32
hotkey tests, reported as one skip — `92 passed, 1 skipped`). The macOS hotkey
parser is tested on both.

These checks need a real desktop session and are not part of the suite:

```bash
.venv\Scripts\python.exe scripts\check_selection.py     # Win32 capture path
.venv\Scripts\python.exe scripts\check_end_to_end.py    # hotkey to popup
```

On macOS, the capture path (needs Accessibility for the terminal that runs it;
without it the script stops at check 0):

```bash
.venv.nosync/bin/python scripts/check_selection_macos.py
```

All three open **their own** windows. They never drive an application you
already have open. Nothing checks the macOS hotkey-to-popup path automatically:
posting the hotkey itself would need the same permission, so that one is tested
by hand.
