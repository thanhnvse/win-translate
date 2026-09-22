# win-translate

A background tray app for Windows. Select text in any application, press a
hotkey, and a small popup shows the translation next to the cursor: English in,
Vietnamese out — and Vietnamese in, English out.

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
(`NSServices` in `Info.plist`). This repo is Windows-only for now.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

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

## Configuration

Written on first run to `%APPDATA%\win-translate\config.json`, and reachable
from the tray menu:

| Key | Default | Notes |
| --- | --- | --- |
| `hotkey` | `ctrl+alt+t` | e.g. `ctrl+shift+k`, `ctrl+alt+f2`. Needs at least one modifier. |
| `target_language` | `vi` | Any Google Translate language code. |
| `alternate_language` | `en` | Where a selection that is *already* Vietnamese goes. Set to `""` to disable the reverse direction. |
| `google_api_key` | `""` | Empty uses the free endpoints. Set it to use Cloud Translation API v2. |
| `popup_width` | `460` | Pixels. |
| `popup_max_height` | `420` | The popup grows with the text up to this, then scrolls. |
| `show_detected_language` | `true` | Shows `ENGLISH → VIETNAMESE` in the popup heading. |

Restart the app after editing.

`ctrl+shift+t` is a deliberate non-default: a global hotkey outranks an
application's own shortcut, so it would take "reopen closed tab" away from every
browser.

## How it works

* **Hotkey** — Win32 `RegisterHotKey` on a dedicated thread with its own message
  loop. Not a keyboard hook: a hook would see every keystroke the user types,
  including passwords, and need elevation to watch elevated apps.
* **Selection** — Windows cannot be asked what another process has selected, so
  the app saves the clipboard, synthesises Ctrl+C into the focused window, waits
  for `GetClipboardSequenceNumber` to move, reads the text, and puts the old
  clipboard back. Modifiers still physically held from the hotkey are released
  first, or the target app would receive Ctrl+Alt+C instead of a copy.
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
* **Apps that do not support Ctrl+C** (some custom controls, PDF viewers in
  protected mode) return nothing, and the popup says so.

## Tests

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

84 tests, no network and no display needed — Qt runs under the `offscreen`
platform, and the translation tests use a fake HTTP session.

Two checks need a real desktop session and are not part of the suite:

```bash
.venv\Scripts\python.exe scripts\check_selection.py     # Win32 capture path
.venv\Scripts\python.exe scripts\check_end_to_end.py    # hotkey to popup
```

Both open **their own** windows. They never drive an application you already
have open.
