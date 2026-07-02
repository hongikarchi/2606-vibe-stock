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

import datetime
import json
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # fail messages carry Korean macro names
except Exception:  # noqa: BLE001
    pass

DATA = pathlib.Path(__file__).resolve().parents[1] / "web" / "public" / "data"

# Loose floors — well below normal (graph ~400, themes 76, emergent 120). A breach means
# something structurally broke (empty export, missing reanalyze), not normal variation.
FLOOR = {"graph_issuers": 380, "themes_nodes": 70, "emergent_terms": 100}

# W1-W3 structural invariants (2026-07-03): these fields are now product surface — their
# absence means the export ran with pre-upgrade code or the capture layer silently died.
MACRO_MDD_MIN = 8            # of 12 macros must carry a 1y MDD (N-of-M, feed-lag tolerant)
TURNOVER_ROWS_MIN = 5        # per market (10 normal; 5 = loose floor)
MKTCAP_MIN_PCT = 25.0        # % of graph issuers with mktcap>0 (KR-only ≈ 30%; US seed lifts it)

# FRESHNESS — the 2026-07-02 audit found the 7 core macros frozen at 06-18/06-23 under an
# 07-02 label (they were only refreshed by loop_build, never by the cron). market_refresh.py
# fixes the refresh; these floors make the class of silent staleness unshippable.
#
# N-of-M, not per-macro veto (adversarial review 2026-07-02): a single stale macro is
# upstream FEED LAG (^TNX verified 4 sessions behind at Yahoo itself — refetching cannot
# heal it), and giving one third-party feed a veto over ALL shipping (news/themes included)
# would block the long weekend. 1-2 stale = tolerated here, surfaced as WARN by
# quality_report.py. >=MACRO_STALE_MAX stale = the refresh MECHANISM broke (the original
# all-frozen defect fired with 7) -> block.
MACRO_FRESH_DAYS = 7          # weekend + market-holiday tolerant
MACRO_STALE_MAX = 3           # fail at >=3 stale macros (mechanism failure, not feed lag)
PRICE_FRESH_FLOOR_PCT = 60.0  # share of price series fresh within 7d (dead tickers exist)

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

    # 7. FRESHNESS — macro windows must end near as_of, and the price layer as a whole
    #    must be mostly fresh (the label==content invariant, extended to market data).
    #    N-of-M: single-feed lag tolerated (upstream latency, self-heals when the source
    #    publishes); multi-macro staleness = refresh mechanism broke -> block.
    if as_of:
        as_of_d = datetime.date.fromisoformat(as_of[:10])
        macros = dash.get("macros", [])
        stale, dateless = [], 0
        for m in macros:
            end = (m.get("end") or "")[:10]
            try:
                age = (as_of_d - datetime.date.fromisoformat(end)).days
            except ValueError:
                dateless += 1
                continue
            if age > MACRO_FRESH_DAYS:
                stale.append(f"{m.get('name')}={end}(+{age}d)")
        if not macros:
            fails.append("[fresh] dashboard.macros is empty — macro layer missing from export")
        elif dateless == len(macros):
            fails.append("[fresh] no macro carries a window-end date — dashboard built by "
                         "pre-freshness-fix code; rebuild artifacts")
        elif len(stale) >= MACRO_STALE_MAX:
            fails.append(f"[fresh] {len(stale)} macro series stale >{MACRO_FRESH_DAYS}d vs "
                         f"as_of {as_of_day} (mechanism failure at >={MACRO_STALE_MAX}): "
                         + ", ".join(stale[:5]))
        pf = meta.get("price_fresh_pct")
        if pf is None:
            fails.append("[fresh] meta.price_fresh_pct missing — rebuild artifacts with "
                         "current export_artifacts.py")
        elif pf < PRICE_FRESH_FLOOR_PCT:
            fails.append(f"[fresh] price_fresh_pct={pf} < {PRICE_FRESH_FLOOR_PCT} — "
                         "price windows mostly stale (did market_refresh run?)")

    # 8. W1-W3 SURFACE — MDD/거래대금/급상승/시총/라벨 are product surface now; regressions
    #    here shipped silently before (label==content, extended)
    mdd_n = sum(1 for m in dash.get("macros", []) if isinstance(m.get("mdd"), (int, float)))
    if mdd_n < MACRO_MDD_MIN:
        fails.append(f"[w1] only {mdd_n} macros carry mdd (need >={MACRO_MDD_MIN}) — "
                     "1y capture broken?")
    tt = dash.get("turnover_top") or {}
    for mk in ("kr", "us"):
        if len(tt.get(mk) or []) < TURNOVER_ROWS_MIN:
            fails.append(f"[w1] turnover_top.{mk} has {len(tt.get(mk) or [])} rows "
                         f"(need >={TURNOVER_ROWS_MIN}) — 거래대금 capture broken?")
    if "rising" not in themes:
        fails.append("[w2] themes.rising missing — surge layer not exported")
    no_summary = sum(1 for e in themes.get("edges", []) if not e.get("summary"))
    if no_summary:
        fails.append(f"[w2] {no_summary} theme edges lack a summary — the auto-template "
                     "fallback is structurally guaranteed; its absence means the builder broke")
    # exact-duplicate heads within one list = the dedup layer regressed
    def _dups(lists):
        return sum(1 for hs in lists
                   if len({h.get("t") for h in hs}) < len(hs))
    dup_lists = _dups([n.get("heads", []) for n in themes.get("nodes", [])])
    dup_lists += _dups([i.get("heads", []) for i in graph.get("issuers", [])])
    if dup_lists:
        fails.append(f"[w2] {dup_lists} heads lists contain exact-duplicate headlines — "
                     "headline_dedup regressed")
    ksic_raw = sum(1 for i in graph.get("issuers", [])
                   if re.match(r"KSIC \d", str(i.get("sector") or "")))
    if ksic_raw:
        fails.append(f"[w3] {ksic_raw} KR issuers ship raw KSIC codes as sector labels")
    cap_n = sum(1 for i in graph.get("issuers", []) if (i.get("mktcap") or 0) > 0)
    cap_pct = round(100 * cap_n / (n_issuers or 1), 1)
    if cap_pct < MKTCAP_MIN_PCT:
        fails.append(f"[w3] mktcap coverage {cap_pct}% < {MKTCAP_MIN_PCT}% — "
                     "treemap sizing starved (KRX snapshot / US seed broken?)")

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
