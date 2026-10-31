"""Entry point of the packaged app, the one PyInstaller freezes.

The same as ``python -m wintranslate``, plus ``--self-check REPORT``, which the
release build runs on the frozen app before shipping it.
"""

import sys
from pathlib import Path

if len(sys.argv) >= 3 and sys.argv[1] == "--self-check":
    from wintranslate.selfcheck import run

    sys.exit(run(Path(sys.argv[2])))

from wintranslate.app import main

sys.exit(main())
