"""verify_artifacts.py — objective non-regression GATE for the published artifacts.

    python pipelines/verify_artifacts.py            # exit 0 = safe to ship, !=0 = block

The permanent form of "never ship label != content again". Run it BEFORE any commit/deploy
of web/public/data (both the autonomous loop AND run_pipeline.bat call it). It encodes the
invariants the info-quality audit fought for (INFO_AUDIT_2026-06-28.md):

  - all 5 artifacts parse and meet a size floor (catches empty/partial exports)
  - RETENTION: known-good entities/themes survive (catches OVER-removal — a removal-only
    check misses silently-dropped topics; the emergent stoplist work proved this)
  - LABEL == CONTENT: meta.as_of == dashboard.as_of, and no displayed headline post-dates
    as_of (the dominant audit defect: a fresh-looking label over stale/uncovered content)
  - graph.issuers > 0  (the exact empty-graph bug from running export without reanalyze at
    the advanced as_of — AnalysisResult is matched on an EXACT as_of key)

Pure stdlib, reads only web/public/data/*.json (no DB), so it is fast and side-effect-free.
Thresholds are deliberately LOOSE floors (regression detection, not exact-value asserts) —
the loop's own baseline-metric comparison handles drift; this is the hard floor.
"""
from __future__ import annotations

import json
import pathlib
import sys

DATA = pathlib.Path(__file__).resolve().parents[1] / "web" / "public" / "data"

# Loose floors — well below normal (graph ~400, themes 52, emergent 120). A breach means
# something structurally broke (empty export, missing reanalyze), not normal variation.
FLOOR = {"graph_issuers": 380, "themes_nodes": 50, "emergent_terms": 100}

# Retention guards (catch OVER-removal). These MUST appear in the published artifacts.
# KR bellwether — its absence is the #2 audit defect AND a canary for empty/misranked KR set.
MUST_HAVE_ISSUER = "하이닉스"
# Core themes — the spine; if a keyword edit silently empties one, retention fails here.
MUST_HAVE_THEMES = {"semiconductor", "ai", "datacenter", "ev_battery"}


def _load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def check() -> list[str]:
    """Return a list of failure strings (empty list = all invariants hold)."""
    fails: list[str] = []

    # 1. all 5 artifacts parse
    arts = {}
    for n in ("meta", "themes", "emergent", "graph", "dashboard"):
        try:
            arts[n] = _load(n)
        except Exception as e:  # noqa: BLE001
            fails.append(f"[parse] {n}.json failed to load: {e}")
    if fails:
        return fails  # can't check further if something won't parse

    meta, themes, emergent, graph, dash = (
        arts["meta"], arts["themes"], arts["emergent"], arts["graph"], arts["dashboard"])

    # 2. size floors (catches empty/partial export)
    n_issuers = len(graph.get("issuers", []))
    n_themes = len(themes.get("nodes", []))
    n_terms = len(emergent.get("terms", []))
    if n_issuers < FLOOR["graph_issuers"]:
        fails.append(f"[floor] graph.issuers={n_issuers} < {FLOOR['graph_issuers']}")
    if n_themes < FLOOR["themes_nodes"]:
        fails.append(f"[floor] themes.nodes={n_themes} < {FLOOR['themes_nodes']}")
    if n_terms < FLOOR["emergent_terms"]:
        fails.append(f"[floor] emergent.terms={n_terms} < {FLOOR['emergent_terms']}")

    # 3. graph.issuers > 0 — the exact empty-graph bug (export ran without reanalyze@as_of)
    if n_issuers == 0:
        fails.append("[empty-graph] graph.issuers == 0 (AnalysisResult missing at this as_of?)")

    # 4. dashboard ranking lists populated
    for k in ("us", "kr", "hot", "cold"):
        if not dash.get(k):
            fails.append(f"[empty] dashboard.{k} is empty")

    # 5. RETENTION — known-good survives (over-removal detection)
    issuer_names = " ".join(i.get("name", "") for i in graph.get("issuers", []))
    if MUST_HAVE_ISSUER not in issuer_names:
        fails.append(f"[retention] issuer '{MUST_HAVE_ISSUER}' (SK하이닉스) absent from graph.json")
    theme_ids = {n.get("id") for n in themes.get("nodes", [])}
    missing_themes = MUST_HAVE_THEMES - theme_ids
    if missing_themes:
        fails.append(f"[retention] core themes missing from themes.json: {sorted(missing_themes)}")

    # 6. LABEL == CONTENT
    as_of = meta.get("as_of")
    if as_of != dash.get("as_of"):
        fails.append(f"[label] meta.as_of={as_of} != dashboard.as_of={dash.get('as_of')}")
    if as_of:
        as_of_day = as_of[:10]
        # no displayed headline may post-date the as_of label (fresh label over future content)
        future = []
        for n in themes.get("nodes", []):
            for h in n.get("heads", []):
                d = (h.get("d") or "")[:10]
                if d and d > as_of_day:
                    future.append(d)
        for i in graph.get("issuers", []):
            for h in i.get("heads", []):
                d = (h.get("d") or "")[:10]
                if d and d > as_of_day:
                    future.append(d)
        if future:
            fails.append(f"[label] {len(future)} displayed headline(s) post-date as_of "
                         f"{as_of_day} (max {max(future)}) — label claims fresher than content allows")

    return fails


def main() -> int:
    fails = check()
    if fails:
        print("ARTIFACT GATE: FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("ARTIFACT GATE: PASS (all invariants hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
