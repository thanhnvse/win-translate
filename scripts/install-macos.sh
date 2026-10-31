#!/bin/sh
# Install or update win-translate from the latest GitHub release:
#
#   curl -fsSL https://raw.githubusercontent.com/thanhnvse/win-translate/main/scripts/install-macos.sh | sh
#
# The same download as the .dmg on the Releases page, fetched with curl instead
# of a browser. curl does not mark files as downloaded from the internet, so
# macOS does not ask for "Open Anyway" -- the step an unnotarized app otherwise
# needs on first launch.
#
# WIN_TRANSLATE_DMG (a URL or file:// path) installs that image instead of the
# latest release; WIN_TRANSLATE_APPS installs somewhere other than /Applications;
# WIN_TRANSLATE_OPEN=0 skips starting the app afterwards.
set -eu

REPO="thanhnvse/win-translate"
APPS="${WIN_TRANSLATE_APPS:-/Applications}"
APP="$APPS/win-translate.app"

if [ "$(id -u)" = 0 ]; then
    # Run as root, the app would be owned by root and started as root.
    echo "Run this without sudo." >&2
    exit 1
fi
mkdir -p "$APPS" 2>/dev/null || true
if [ ! -w "$APPS" ]; then
    echo "Cannot write to $APPS (only administrators can). Install into your own" >&2
    echo "Applications folder instead by adding WIN_TRANSLATE_APPS=\$HOME/Applications" >&2
    echo "before sh, or run this from an administrator account." >&2
    exit 1
fi

case "$(uname -m)" in
    arm64) arch=arm64 ;;
    x86_64) arch=x86_64 ;;
    *) echo "Unsupported Mac: $(uname -m)" >&2; exit 1 ;;
esac

url="${WIN_TRANSLATE_DMG:-}"
if [ -z "$url" ]; then
    url=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | grep -o "https://[^\"]*-macos-$arch\.dmg" | head -n 1 || true)
    if [ -z "$url" ]; then
        echo "The latest release has no macOS ($arch) download." >&2
        exit 1
    fi
fi

work=$(mktemp -d)
mount=""
cleanup() {
    if [ -n "$mount" ]; then hdiutil detach -quiet "$mount" || true; fi
    rm -rf "$work" "$APP.new"
}
trap cleanup EXIT

echo "Downloading $url"
curl -fL --progress-bar -o "$work/win-translate.dmg" "$url"
mount=$(hdiutil attach -nobrowse -readonly "$work/win-translate.dmg" | awk -F '\t' 'END { print $NF }')
if [ ! -d "$mount/win-translate.app" ]; then
    echo "The download does not contain win-translate.app." >&2
    exit 1
fi

# An update: stop the copy running from this very path first, so its files are
# not replaced under it. Matched on the full executable path, not the name, so
# a win-translate started from anywhere else is left alone.
exe="$APP/Contents/MacOS/win-translate"
running=$(ps -axww -o pid=,command= | awk -v exe="$exe" '
    { pid = $1; sub(/^[ \t]*[0-9]+[ \t]+/, "") }
    $0 == exe || index($0, exe " ") == 1 { print pid }')
if [ -n "$running" ]; then
    echo "Quitting the running win-translate"
    kill $running || true
    sleep 2
fi

# Copy beside the old app first, then swap: an interrupted copy leaves the old
# app working instead of no app or half of one. ditto, not cp, keeps the
# bundle's symlinks and its code signature intact.
rm -rf "$APP.new"
ditto "$mount/win-translate.app" "$APP.new"
rm -rf "$APP"
mv "$APP.new" "$APP"
echo "Installed $APP"
if [ "${WIN_TRANSLATE_OPEN:-1}" != 0 ]; then
    open "$APP"
fi
