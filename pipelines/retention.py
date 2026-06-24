"""retention.py — bound the unbounded growth of raw news Claims/Mentions.

    SKG_STORAGE_BACKEND=neo4j python pipelines/retention.py            # DRY-RUN (default, safe)
    SKG_STORAGE_BACKEND=neo4j python pipelines/retention.py --prune    # actually delete

Insight: the per-day :ThemeDay aggregate is the DURABLE temporal signal — once a news
headline's day-bucket count is recorded, the raw :Claim/:Mention behind it is only needed
for the panel's "recent headlines" view. So raw news older than RETENTION_DAYS can be pruned
WITHOUT losing the trend/decay data (ThemeDay persists). EDGAR filing claims are NOT pruned
(they're the issuer-event record, low volume, permanent).

DEFAULT IS DRY-RUN (prints what would go, deletes nothing). Pruning is destructive → needs
the explicit --prune flag AND a backup (run export_artifacts.py first). Aggregates survive.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import datetime
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.database import make_repo

RETENTION_DAYS = int(os.environ.get("SKG_RETENTION_DAYS", "120"))


def main() -> None:
    prune = "--prune" in sys.argv
    repo = make_repo(cfg)

    # cutoff = AS_OF_NOW - RETENTION_DAYS (deterministic; lexical ISO compare like the rest)
    now = datetime.date.fromisoformat(cfg.AS_OF_NOW[:10])
    cutoff = (now - datetime.timedelta(days=RETENTION_DAYS)).isoformat() + "T00:00:00"
    print(f"[retention] RETENTION_DAYS={RETENTION_DAYS} → cutoff {cutoff[:10]} "
          f"({'PRUNE' if prune else 'DRY-RUN'})")

    # what would be pruned: news claims/mentions older than cutoff
    old_claims = repo._read(
        "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' AND cl.event_time < $c "
        "RETURN count(cl) AS n", c=cutoff)[0]["n"]
    old_ments = repo._read(
        "MATCH (m:Mention) WHERE m.source_id STARTS WITH 'news::' AND m.event_time < $c "
        "RETURN count(m) AS n", c=cutoff)[0]["n"]
    # confirm aggregates survive: ThemeDay buckets before the cutoff still exist
    old_buckets = repo._read(
        "MATCH (d:ThemeDay) WHERE d.day < $c RETURN count(d) AS n", c=cutoff[:10])[0]["n"]

    print(f"[retention] news claims older than cutoff:   {old_claims}")
    print(f"[retention] news mentions older than cutoff: {old_ments}")
    print(f"[retention] :ThemeDay buckets before cutoff (PRESERVED — the trend signal): {old_buckets}")

    if not prune:
        print("[retention] DRY-RUN — nothing deleted. Re-run with --prune to apply.")
        print("[retention] (the ThemeDay aggregate keeps the temporal/decay signal intact)")
        repo.close()
        return

    # PRUNE: delete old raw news claims/mentions; ThemeDay/prices/rankings untouched.
    repo._write(
        "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' AND cl.event_time < $c "
        "DETACH DELETE cl", c=cutoff)
    repo._write(
        "MATCH (m:Mention) WHERE m.source_id STARTS WITH 'news::' AND m.event_time < $c "
        "DETACH DELETE m", c=cutoff)
    remain = repo._read("MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' RETURN count(cl) AS n")[0]["n"]
    print(f"[retention] pruned. remaining news claims: {remain}  (ThemeDay aggregates intact)")
    repo.close()


if __name__ == "__main__":
    main()
