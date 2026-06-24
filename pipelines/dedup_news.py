"""dedup_news.py — ONE-TIME cleanup of duplicate news Claims/Mentions.

    SKG_STORAGE_BACKEND=neo4j python pipelines/dedup_news.py

The old hash()-based doc_id was per-process randomized, so the same article URL got a
different doc_id on each pull → duplicate Claim/Mention nodes (ratio ~1.54). doc_id is now
fix-forward (sha1), so this clears the pre-existing debt. Keeps the lexicographically-lowest
claim_id per content group (source_span + subject_id + relation), DETACH DELETEs the rest.

DESTRUCTIVE. Run pipelines/export_artifacts.py first (it writes backups/graph_dump.json.gz).
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
from skg.database import make_repo


def main() -> None:
    repo = make_repo(cfg)

    before = repo._read("MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' RETURN count(cl) AS c")[0]["c"]
    mbefore = repo._read("MATCH (m:Mention) WHERE m.source_id STARTS WITH 'news::' RETURN count(m) AS c")[0]["c"]
    print(f"[dedup] before: {before} news claims, {mbefore} news mentions")

    # Claims: group by content key, keep lowest claim_id, delete the rest. Batched DETACH DELETE.
    repo._write(
        "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
        "WITH cl.source_span AS span, cl.subject_id AS subj, cl.relation AS rel, "
        "     collect(cl) AS group "
        "WHERE size(group) > 1 "
        "WITH [c IN group | c] AS group "
        "UNWIND group AS c "
        "WITH group, c ORDER BY c.claim_id "
        "WITH group, head(collect(c)) AS keep "
        "UNWIND group AS c "
        "WITH keep, c WHERE c <> keep "
        "DETACH DELETE c")

    # Mentions: same dedup by (source_span, surface_form, resolved_target_id)
    repo._write(
        "MATCH (m:Mention) WHERE m.source_id STARTS WITH 'news::' "
        "WITH m.source_span AS span, m.surface_form AS sf, m.resolved_target_id AS tid, "
        "     collect(m) AS group "
        "WHERE size(group) > 1 "
        "UNWIND group AS x "
        "WITH group, x ORDER BY x.mention_id "
        "WITH group, head(collect(x)) AS keep "
        "UNWIND group AS x "
        "WITH keep, x WHERE x <> keep "
        "DETACH DELETE x")

    after = repo._read("MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' RETURN count(cl) AS c")[0]["c"]
    mafter = repo._read("MATCH (m:Mention) WHERE m.source_id STARTS WITH 'news::' RETURN count(m) AS c")[0]["c"]
    distinct = repo._read("MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
                          "RETURN count(DISTINCT cl.source_span) AS c")[0]["c"]
    print(f"[dedup] after:  {after} news claims (-{before - after}), {mafter} mentions (-{mbefore - mafter})")
    print(f"[dedup] distinct headlines: {distinct} → ratio {after / distinct:.3f} (target ~1.0)")
    repo.close()


if __name__ == "__main__":
    main()
