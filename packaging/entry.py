"""Entry point of the packaged app, the one PyInstaller freezes.

The same as ``python -m wintranslate``, plus ``--self-check REPORT``, which the
release build runs on the frozen app before shipping it, and ``--speak-test
REPORT [CODE [VOLUME]]``, which reads a sentence aloud for a person to hear.
"""

import sys
from pathlib import Path


def _self_check(report: Path) -> int:
    from wintranslate.selfcheck import run

    return run(report)


def _speak_test(report: Path) -> int:
    # win-translate --speak-test REPORT [CODE [VOLUME]]; see selfcheck.speak_test.
    from wintranslate.selfcheck import speak_test

    code = sys.argv[3] if len(sys.argv) > 3 else "vi"
    volume = float(sys.argv[4]) if len(sys.argv) > 4 else None
    return speak_test(report, code, volume)


_CHECKS = {"--self-check": _self_check, "--speak-test": _speak_test}

if len(sys.argv) >= 3 and sys.argv[1] in _CHECKS:
    report = Path(sys.argv[2])
    try:
        sys.exit(_CHECKS[sys.argv[1]](report))
    except Exception:
        # An escaped exception would open PyInstaller's modal traceback dialog
        # in a windowed build and stall the release; write it down instead.
        import traceback

        report.write_text("FAIL self-check crashed:\n" + traceback.format_exc(), encoding="utf-8")
        sys.exit(2)

from wintranslate.app import main

sys.exit(main())
