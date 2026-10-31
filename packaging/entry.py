"""Entry point of the packaged app, the one PyInstaller freezes.

The same as ``python -m wintranslate``, plus ``--self-check REPORT``, which the
release build runs on the frozen app before shipping it.
"""

import sys
from pathlib import Path

if len(sys.argv) >= 3 and sys.argv[1] == "--self-check":
    report = Path(sys.argv[2])
    try:
        from wintranslate.selfcheck import run

        sys.exit(run(report))
    except Exception:
        # An escaped exception would open PyInstaller's modal traceback dialog
        # in a windowed build and stall the release; write it down instead.
        import traceback

        report.write_text("FAIL self-check crashed:\n" + traceback.format_exc(), encoding="utf-8")
        sys.exit(2)

from wintranslate.app import main

sys.exit(main())
