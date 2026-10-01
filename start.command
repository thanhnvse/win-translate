#!/bin/sh
# Double-click in Finder to start win-translate in the background.
# cd first: "-m wintranslate" resolves the package from the working directory.
cd "$(dirname "$0")" || exit 1
# .venv.nosync, not .venv: see "Install" in README.md.
if [ ! -x .venv.nosync/bin/python ]; then
    echo "No virtualenv at .venv.nosync -- follow Install in README.md first." >&2
    exit 1
fi
# nohup + & so closing this Terminal window does not take the app with it.
# The log sits outside the repo, where iCloud would otherwise sync it.
LOG="$HOME/Library/Logs/win-translate.log"
nohup .venv.nosync/bin/python -m wintranslate >>"$LOG" 2>&1 &
# A missing dependency kills it within a second; say so instead of "started".
sleep 1
if ! kill -0 $! 2>/dev/null; then
    echo "win-translate failed to start. See $LOG" >&2
    exit 1
fi
echo "win-translate started. Log: $LOG"
