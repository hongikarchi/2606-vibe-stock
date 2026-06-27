"""mine_phrase_candidates.py — CODE half of the issue hierarchy: mine per-parent phrase
candidates from the live graph's headlines and dump them for the session to curate.

    SKG_STORAGE_BACKEND=neo4j python pipelines/mine_phrase_candidates.py

Writes data/phrase_candidates.json: {parent_id: {label, n_headlines, candidates:[{phrase,
count, lift, score}], sample_headlines:[...]}}. The session (Claude) reads this and authors
data/subthemes.json — clean child themes per parent. Deterministic, key-free, idempotent.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze.phrases import mine_candidates
from skg.analyze.themes import THEMES, label_of, themes_in
from skg.database import make_repo

TOP_K = 30
N_SAMPLE = 25  # sample headlines per parent for the curation context


def main() -> None:
    repo = make_repo(cfg)
    from skg.sources.news import is_quality_outlet
    rows = repo._read(
        "MATCH (cl:Claim)-[:FROM_SOURCE]->(src:Source) WHERE cl.source_id STARTS WITH 'news::' "
        "RETURN cl.source_span AS h, src.name AS outlet")
    heads = [r["h"] for r in rows if r["h"] and is_quality_outlet(r["outlet"])]
    print(f"[mine] {len(heads)} headlines (vetted press only)")

    # bucket headlines by parent theme (a headline can be in several)
    buckets: dict[str, list[str]] = {tid: [] for tid in THEMES}
    for h in heads:
        for tid in themes_in(h):
            if tid in buckets:
                buckets[tid].append(h)

    out = {}
    for tid in THEMES:
        bucket = buckets[tid]
        if len(bucket) < 8:
            continue
        cand = mine_candidates(bucket, heads, top_k=TOP_K)
        out[tid] = {
            "label": label_of(tid),
            "n_headlines": len(bucket),
            "candidates": cand,
            "sample_headlines": bucket[:N_SAMPLE],
        }
        gems = ", ".join(c["phrase"] for c in cand[:5])
        print(f"[mine] {label_of(tid):16} {len(bucket):4}건 → {len(cand)} 후보  top: {gems}")

    p = cfg.ROOT / "data" / "phrase_candidates.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[mine] -> {p}  ({len(out)} parents)")
    repo.close()


if __name__ == "__main__":
    main()
