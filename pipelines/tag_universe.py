"""tag_universe.py — tag index membership on US issuers (junk-cut, 작업2).

    SKG_STORAGE_BACKEND=neo4j python pipelines/tag_universe.py            # tag only (safe)
    SKG_STORAGE_BACKEND=neo4j python pipelines/tag_universe.py --prune-dry # show what prune would cut
    SKG_STORAGE_BACKEND=neo4j python pipelines/tag_universe.py --prune     # DESTRUCTIVE: drop out-of-universe US issuers

Step 1 (tag) is non-destructive: stamps index_membership on S&P500 ∪ NASDAQ-100 issuers.
Step 3 (prune) is DESTRUCTIVE and gated behind --prune: DETACH DELETE US issuers with no
membership (the micro-cap junk polluting associations). KR is left untouched (already top-300).
NEWS/MACRO ingestion is unaffected — only the per-company issuer universe is narrowed.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze.universe import us_universe_ciks
from skg.database import make_repo


def main() -> None:
    mode = "tag"
    if "--prune-dry" in sys.argv:
        mode = "prune-dry"
    elif "--prune" in sys.argv:
        mode = "prune"

    repo = make_repo(cfg)

    # always (re)tag first — idempotent
    print("[universe] fetching S&P500 + NASDAQ-100 constituents (key-free)...")
    ciks = us_universe_ciks()
    print(f"[universe] {len(ciks)} index CIKs (S&P500 ∪ NASDAQ-100)")
    # restrict to CIKs actually in our graph
    ours = {r["i"] for r in repo._read(
        "MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH 'CIK' RETURN i.issuer_id AS i")}
    present = {c: m for c, m in ciks.items() if c in ours}
    repo.set_index_membership(present)
    print(f"[universe] tagged {len(present)} in-graph US issuers as index members")

    in_uni = len(present)
    total_us = len(ours)
    out_uni = total_us - in_uni
    print(f"[universe] US issuers: {total_us} total  →  {in_uni} in-universe  /  {out_uni} junk (out)")

    if mode == "tag":
        print("[universe] tag-only mode. Run with --prune-dry to preview the cut, --prune to execute.")
        repo.close()
        return

    # what would be pruned: US issuers with no membership tag
    junk = repo._read(
        "MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH 'CIK' AND i.index_membership IS NULL "
        "RETURN count(i) AS n")[0]["n"]
    sample = repo._read(
        "MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH 'CIK' AND i.index_membership IS NULL "
        "RETURN i.name AS n LIMIT 10")
    print(f"[universe] PRUNE would DETACH DELETE {junk} out-of-universe US issuers, e.g.:")
    for r in sample:
        print(f"            - {r['n']}")

    if mode == "prune-dry":
        print("[universe] DRY RUN — nothing deleted. Re-run with --prune to execute (after backup).")
        repo.close()
        return

    # DESTRUCTIVE
    print("[universe] PRUNING (DETACH DELETE out-of-universe US issuers + their orphaned docs)...")
    repo._write(
        "MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH 'CIK' AND i.index_membership IS NULL "
        "DETACH DELETE i")
    print(f"[universe] pruned. nodes now = {repo.node_count()}")
    print("[universe] NEXT: re-run reanalyze so PPR/associations reflect the clean universe.")
    repo.close()


if __name__ == "__main__":
    main()
