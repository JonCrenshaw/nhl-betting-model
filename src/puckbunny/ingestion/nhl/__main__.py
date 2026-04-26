"""Entry point for ``python -m puckbunny.ingestion.nhl``.

Delegates to :func:`puckbunny.ingestion.nhl.cli.main`. Kept as a thin
shim so the CLI module is independently testable without invoking
``runpy``.
"""

from __future__ import annotations

import sys

from puckbunny.ingestion.nhl.cli import main

if __name__ == "__main__":
    sys.exit(main())
