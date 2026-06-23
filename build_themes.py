"""build_themes.py — build the THEME ASSOCIATION layer from stored news.

    SKG_STORAGE_BACKEND=neo4j python build_themes.py

This is the layer the user actually wants: fragmented market info connected into a web they
can reason over. From the news headlines already in the graph it builds:
  :Theme nodes (AI, 반도체, 데이터센터, 전력, 금리, 환율, 유가, 이란/지정학, 트럼프, ...)
  (:Theme)-[:CO_OCCURS {weight}]->(:Theme)        — two themes in the same headline
  (:Theme)-[:MENTIONED_WITH {weight}]->(:Issuer)  — theme anchored to the entity it was about

Everything is OBSERVED CO-OCCURRENCE, never asserted causation — the human reads the web and
infers the story (이란→유가→환율→반도체). Idempotent (MERGE). Run after news pulls.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from itertools import combinations

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze.themes import label_of, themes_in
from skg.store import make_repo

MIN_COOCCUR = 4   # drop one-off pairs (noise); keep edges seen in >= N headlines


def main() -> None:
    repo = make_repo(cfg)
    repo.init_schema()

    # every news claim: its headline (source_span) + the entity it was about (subject_id)
    rows = repo._read(
        "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
        "RETURN cl.source_span AS headline, cl.subject_id AS subject")
    print(f"[themes] scanning {len(rows)} news headlines...")

    freq = Counter()
    cooc = Counter()
    theme_entity = Counter()
    for r in rows:
        ts = themes_in(r["headline"] or "")
        if not ts:
            continue
        for t in ts:
            freq[t] += 1
            if r["subject"] and not str(r["subject"]).startswith("provisional::"):
                theme_entity[(t, r["subject"])] += 1
        for a, b in combinations(sorted(ts), 2):
            cooc[(a, b)] += 1

    # 1) theme nodes
    themes = [{"theme_id": t, "label": label_of(t), "freq": f} for t, f in freq.items()]
    repo.write_themes(themes)
    print(f"[themes] {len(themes)} themes  (top: "
          f"{', '.join(label_of(t) for t, _ in freq.most_common(5))})")

    # 2) co-occurrence edges (themes that share headlines) — the association web
    cooc_edges = [{"a": a, "b": b, "weight": w} for (a, b), w in cooc.items() if w >= MIN_COOCCUR]
    repo.write_theme_cooccurrence(cooc_edges)
    print(f"[themes] {len(cooc_edges)} CO_OCCURS edges (weight>={MIN_COOCCUR})")
    print("[themes] strongest theme associations (the chains you can reason over):")
    for (a, b), w in sorted(((e, cooc[e]) for e in cooc if cooc[e] >= MIN_COOCCUR),
                            key=lambda x: -x[1])[:12]:
        print(f"    {label_of(a)} ─ {label_of(b)}  ({w} 헤드라인)")

    # 3) theme -> entity anchors (keep meaningful ones)
    te_edges = [{"theme_id": t, "entity_id": e, "weight": w}
                for (t, e), w in theme_entity.items() if w >= 2]
    repo.write_theme_entity(te_edges)
    print(f"[themes] {len(te_edges)} theme->entity anchors")

    print(f"[themes] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
