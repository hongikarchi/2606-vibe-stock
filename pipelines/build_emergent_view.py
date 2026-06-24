"""build_emergent_view.py — regenerate out/emergent.html (data-driven term network).

    SKG_STORAGE_BACKEND=neo4j python pipelines/build_emergent_view.py

Wraps skg.export.emergent_graph (previously only invoked via inline -c). Renders the
:Term co-occurrence network with community-detected clusters. Run build_emergent.py first
to (re)compute the :Term nodes from news, then this to draw them.
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import config as cfg
from skg.database import make_repo
from skg.export.emergent_graph import write_emergent_graph


def main() -> None:
    repo = make_repo(cfg)
    summary = write_emergent_graph(repo, cfg.OUT / "emergent.html")
    print(f"[emergent-view] -> {summary['path']}  "
          f"({summary['terms']} terms, {summary['edges']} edges, {summary['clusters']} clusters)")
    repo.close()


if __name__ == "__main__":
    main()
