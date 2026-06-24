"""build_dashboard.py — regenerate out/dashboard.html (market-state one-pager).

    SKG_STORAGE_BACKEND=neo4j python pipelines/build_dashboard.py

Wraps skg.export.dashboard (previously only invoked via inline -c). Reads the live graph
(52w breadth, commodity/macro prices + trend sparklines, hot/cold sectors, live themes).
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

from pathlib import Path

import config as cfg
from skg.database import make_repo
from skg.export.dashboard import write_dashboard


def main() -> None:
    repo = make_repo(cfg)
    summary = write_dashboard(repo, cfg.OUT / "dashboard.html", cfg.AS_OF_NOW)
    print(f"[dashboard] -> {summary['path']}  "
          f"(US breadth {summary['us_breadth']}, {summary['macros']} macro, {summary['sectors']} sectors)")
    repo.close()


if __name__ == "__main__":
    main()
