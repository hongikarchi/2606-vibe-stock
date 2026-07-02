"""export_artifacts.py — emit the React app's data + a full graph backup.

    SKG_STORAGE_BACKEND=neo4j python pipelines/export_artifacts.py

Produces (under web/public/data/, committed to git so it's durable + shareable + the
frontend's data source — no served DB needed):
  graph_dump.json   — FULL node+relationship backup (data-loss safety net)
  themes.json       — theme association view (nodes/edges/summaries/drilldown/decay/trend)
  dashboard.json    — market-state (breadth, commodities+trend, sectors, terms)
  emergent.json     — data-driven term network (terms/edges/clusters)
  graph.json        — top-N issuer graph (issuers/sectors/macro)
  meta.json         — counts + build timestamp source (cfg.AS_OF_NOW)

This is the build-time → serve-time seam: Neo4j is queried HERE (build); the deployed
React app only reads these static JSON files.
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import datetime
import gzip
import json
from pathlib import Path

import config as cfg
from skg.database import make_repo

OUT = cfg.ROOT / "web" / "public" / "data"   # small view JSONs — committed, served to React
BACKUPS = cfg.ROOT / "backups"               # full graph dump — large, gitignored


def _write(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kb = p.stat().st_size / 1024
    print(f"  {name:18} {kb:8.1f} KB")


def _write_backup_gz(name: str, obj) -> None:
    """Full graph dump → compressed in backups/ (data-loss safety net; not in web bundle)."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    p = BACKUPS / name
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(p, "wb") as f:
        f.write(raw)
    mb = p.stat().st_size / 1024 / 1024
    print(f"  {name:24} {mb:6.1f} MB (gzip, backups/)")


def dump_full_graph(repo) -> dict:
    """FULL backup: every node (label+props) + every relationship. The data-loss safety net."""
    nodes = repo._read(
        "MATCH (n) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
    rels = repo._read(
        "MATCH (a)-[r]->(b) RETURN id(a) AS s, id(b) AS t, type(r) AS type, properties(r) AS props")
    return {
        "nodes": [{"id": n["id"], "labels": n["labels"], "props": dict(n["props"])} for n in nodes],
        "rels": [{"s": r["s"], "t": r["t"], "type": r["type"], "props": dict(r["props"])} for r in rels],
    }


def price_fresh_pct(repo, as_of: str, days: int = 7) -> float:
    """Share of :PriceSeries whose window ends within `days` of as_of — the gate's floor
    against the silent-staleness class (price layer frozen under a fresh-looking label)."""
    rows = repo._read("MATCH (p:PriceSeries) RETURN p.window_end AS we")
    if not rows:
        return 0.0
    d0 = datetime.date.fromisoformat(as_of[:10])
    ok = 0
    for r in rows:
        try:
            if (d0 - datetime.date.fromisoformat(str(r["we"])[:10])).days <= days:
                ok += 1
        except (ValueError, TypeError):
            pass
    return round(100 * ok / len(rows), 1)


def main() -> None:
    repo = make_repo(cfg)
    print("[artifacts] dumping full graph (backup, compressed)...")
    full = dump_full_graph(repo)
    _write_backup_gz("graph_dump.json.gz", full)
    print(f"  -> {len(full['nodes'])} nodes, {len(full['rels'])} rels backed up")

    # per-view artifacts (reuse the existing build logic, but emit DATA not HTML)
    print("[artifacts] emitting per-view JSON...")
    from artifact_views import build_theme_data, build_dashboard_data, build_emergent_data, build_graph_data
    _write("themes.json", build_theme_data(repo))
    _write("dashboard.json", build_dashboard_data(repo))
    _write("emergent.json", build_emergent_data(repo))
    _write("graph.json", build_graph_data(repo))

    _write("meta.json", {
        "as_of": cfg.AS_OF_NOW,
        "nodes": len(full["nodes"]),
        "rels": len(full["rels"]),
        "price_fresh_pct": price_fresh_pct(repo, cfg.AS_OF_NOW),
        "views": ["themes", "dashboard", "emergent", "graph"],
    })
    print(f"[artifacts] DONE -> {OUT}")
    repo.close()


if __name__ == "__main__":
    main()
