"""quality_report.py — measure the QUALITY of the accumulated data, against baseline.

    SKG_STORAGE_BACKEND=neo4j python pipelines/quality_report.py            # report
    SKG_STORAGE_BACKEND=neo4j python pipelines/quality_report.py --rebase   # accept current as new baseline

The user's operating loop is: build → run → VERIFY the produced data → MEASURE quality →
fix → repeat. verify_artifacts.py is the hard ship/no-ship floor and loop_metrics.py the
published-artifact soft baseline; this report is the third layer — it measures the SOURCE
data (Neo4j) directly, so quality holes that artifacts hide (e.g. the frozen macro windows
of the 2026-07-02 audit, uncovered issuers, creeping duplication) are visible and tracked.

Outputs out/quality_report.md (human) + out/quality_report.json (machine, baseline compare).
Read-only against the graph; deterministic given the same graph + as_of.
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import datetime
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config as cfg
from skg.database import make_repo

OUT_MD = cfg.OUT / "quality_report.md"
OUT_JSON = cfg.OUT / "quality_report.json"
BASELINE = cfg.OUT / "quality_baseline.json"

# thresholds: LOOSE, aligned with the artifact gate where both exist
MACRO_FRESH_DAYS = 7
PRICE_FRESH_FLOOR_PCT = 60.0
NEWS_FRESH_DAYS = 2          # pipeline liveness: cron runs 3x/day
DUP_RATIO_CEIL = 1.05        # news claims per distinct headline (target ~1.0)


def _age(iso: str | None, as_of: str) -> int:
    try:
        return (datetime.date.fromisoformat(as_of[:10])
                - datetime.date.fromisoformat(str(iso)[:10])).days
    except (ValueError, TypeError):
        return 9999


def _one(repo, cypher: str, **params):
    rows = repo._read(cypher, **params)
    return rows[0] if rows else {}


def collect(repo, as_of: str) -> dict:
    q: dict = {"as_of": as_of}

    # ---- 신선도 (source-of-truth freshness) ------------------------------------
    macros = repo._read("MATCH (m:MacroIndicator) RETURN m.name AS name, m.window_end AS we "
                        "ORDER BY m.window_end")
    macro_ages = {m["name"]: _age(m["we"], as_of) for m in macros}
    prices = repo._read("MATCH (p:PriceSeries) RETURN p.window_end AS we")
    p_fresh = sum(1 for p in prices if _age(p["we"], as_of) <= MACRO_FRESH_DAYS)
    news = _one(repo, "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
                      "RETURN max(cl.knowledge_time) AS kt, max(cl.event_time) AS et, "
                      "count(cl) AS n")
    ar = _one(repo, "MATCH (a:AnalysisResult) RETURN max(a.as_of) AS latest")
    td = _one(repo, "MATCH (t:ThemeDay) RETURN max(t.day) AS latest")
    q["freshness"] = {
        "macro_n": len(macros),
        "macro_stale": sorted(n for n, a in macro_ages.items() if a > MACRO_FRESH_DAYS),
        "macro_max_age_d": max(macro_ages.values()) if macro_ages else None,
        "price_n": len(prices),
        "price_fresh_pct": round(100 * p_fresh / len(prices), 1) if prices else 0.0,
        "news_claims": news.get("n", 0),
        "news_knowledge_age_d": _age(news.get("kt"), as_of),
        "news_event_age_d": _age(news.get("et"), as_of),
        "analysis_latest_as_of": str(ar.get("latest"))[:10],
        "themeday_latest": str(td.get("latest"))[:10],
    }

    # ---- 커버리지 (does the universe actually carry data?) ----------------------
    cov = _one(repo,
        "MATCH (i:Issuer) WHERE (i.issuer_id STARTS WITH 'CIK' AND i.index_membership IS NOT NULL) "
        "   OR i.issuer_id STARTS WITH 'DART' "
        "RETURN count(i) AS n, "
        "sum(CASE WHEN EXISTS {MATCH (:Claim)-[:ABOUT]->(i)} THEN 1 ELSE 0 END) AS with_news, "
        "sum(CASE WHEN EXISTS {MATCH (i)-[:HAS_PRICE]->()} THEN 1 ELSE 0 END) AS with_price, "
        "sum(CASE WHEN i.pos_52w IS NOT NULL THEN 1 ELSE 0 END) AS with_52w, "
        "sum(CASE WHEN EXISTS {MATCH (i)-[:IN_SECTOR]->()} THEN 1 ELSE 0 END) AS with_sector")
    n = cov.get("n") or 1
    q["coverage"] = {
        "universe_issuers": cov.get("n", 0),
        "news_pct": round(100 * (cov.get("with_news") or 0) / n, 1),
        "price_pct": round(100 * (cov.get("with_price") or 0) / n, 1),
        "pos52w_pct": round(100 * (cov.get("with_52w") or 0) / n, 1),
        "sector_pct": round(100 * (cov.get("with_sector") or 0) / n, 1),
    }

    # ---- 중복 (news duplication ratio; target ~1.0) -----------------------------
    dup = _one(repo, "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
                     "RETURN count(cl) AS c, count(DISTINCT cl.source_span) AS d")
    q["duplication"] = {
        "news_claims": dup.get("c", 0),
        "distinct_headlines": dup.get("d", 0),
        "ratio": round((dup.get("c") or 0) / (dup.get("d") or 1), 3),
    }

    # ---- W1-W3 표면 지표 (2026-07-03 배포물 품질 루프) ---------------------------
    krx = _one(repo, "MATCH (i:Issuer) WHERE i.krx_date IS NOT NULL "
                     "RETURN max(i.krx_date) AS d, count(i) AS n")
    cap = _one(repo, "MATCH (i:Issuer) WHERE (i.issuer_id STARTS WITH 'CIK' AND "
                     "i.index_membership IS NOT NULL) OR i.issuer_id STARTS WITH 'DART' "
                     "RETURN count(i) AS n, "
                     "sum(CASE WHEN i.issuer_id STARTS WITH 'DART' AND i.mktcap > 0 "
                     "THEN 1 ELSE 0 END) AS kr_cap, "
                     "sum(CASE WHEN i.issuer_id STARTS WITH 'DART' THEN 1 ELSE 0 END) AS kr_n, "
                     "sum(CASE WHEN i.issuer_id STARTS WITH 'CIK' AND "
                     "(i.shares_outstanding > 0 OR i.mktcap_raw > 0) THEN 1 ELSE 0 END) AS us_cap, "
                     "sum(CASE WHEN i.issuer_id STARTS WITH 'CIK' THEN 1 ELSE 0 END) AS us_n")
    q["w_surface"] = {
        "krx_snapshot_age_d": _age(krx.get("d"), as_of),
        "krx_rows": krx.get("n", 0),
        "mktcap_kr_pct": round(100 * (cap.get("kr_cap") or 0) / (cap.get("kr_n") or 1), 1),
        "mktcap_us_pct": round(100 * (cap.get("us_cap") or 0) / (cap.get("us_n") or 1), 1),
    }
    try:
        themes_art = json.loads((cfg.ROOT / "web" / "public" / "data" / "themes.json")
                                .read_text(encoding="utf-8"))
        edges_art = themes_art.get("edges", [])
        q["w_surface"]["edge_curated_pct"] = round(
            100 * sum(1 for e in edges_art if e.get("summary_kind") == "curated")
            / (len(edges_art) or 1), 1)
        q["w_surface"]["rising_top"] = [r["id"] for r in themes_art.get("rising", [])][:5]
        dash_art = json.loads((cfg.ROOT / "web" / "public" / "data" / "dashboard.json")
                              .read_text(encoding="utf-8"))
        q["w_surface"]["macro_mdd_n"] = sum(
            1 for m in dash_art.get("macros", []) if isinstance(m.get("mdd"), (int, float)))
    except Exception as e:  # noqa: BLE001
        q["w_surface"]["artifact_error"] = f"{type(e).__name__}: {e}"

    # ---- 배포물 건강 (published artifacts; reuse the existing measures) ----------
    try:
        from loop_metrics import metrics as _lm
        q["published"] = _lm()
    except Exception as e:  # noqa: BLE001
        q["published"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        from verify_artifacts import check as _gate
        fails = _gate()
        q["gate"] = {"pass": not fails, "fails": fails}
    except Exception as e:  # noqa: BLE001
        q["gate"] = {"pass": False, "fails": [f"gate crashed: {type(e).__name__}: {e}"]}

    return q


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = v
    return out


def verdicts(q: dict) -> list[tuple[str, str, str]]:
    """(status, metric, note) — PASS/WARN per threshold. WARN is a to-fix flag, not a gate."""
    f, c, d = q["freshness"], q["coverage"], q["duplication"]
    v: list[tuple[str, str, str]] = []

    def chk(ok: bool, name: str, note: str):
        v.append(("PASS" if ok else "WARN", name, note))

    chk(not f["macro_stale"], "macro freshness",
        f"max age {f['macro_max_age_d']}d" + (f", stale: {', '.join(f['macro_stale'][:4])}"
                                              if f["macro_stale"] else ""))
    chk(f["price_fresh_pct"] >= PRICE_FRESH_FLOOR_PCT, "price freshness",
        f"{f['price_fresh_pct']}% of {f['price_n']} series within {MACRO_FRESH_DAYS}d")
    chk(f["news_knowledge_age_d"] <= NEWS_FRESH_DAYS, "news pipeline liveness",
        f"newest knowledge_time {f['news_knowledge_age_d']}d old")
    chk(d["ratio"] <= DUP_RATIO_CEIL, "news duplication",
        f"ratio {d['ratio']} ({d['news_claims']} claims / {d['distinct_headlines']} headlines)")
    w = q.get("w_surface", {})
    if w:
        chk(w.get("krx_snapshot_age_d", 9999) <= 3, "KRX snapshot age",
            f"{w.get('krx_snapshot_age_d')}d old ({w.get('krx_rows')} rows)")
        chk(w.get("mktcap_kr_pct", 0) >= 90, "mktcap coverage KR",
            f"KR {w.get('mktcap_kr_pct')}% · US {w.get('mktcap_us_pct')}%")
        chk(w.get("macro_mdd_n", 0) >= 8, "macro MDD coverage",
            f"{w.get('macro_mdd_n')}/12 macros")
        chk(w.get("edge_curated_pct", 0) >= 50, "theme edge curation",
            f"{w.get('edge_curated_pct')}% curated (나머지는 자동 템플릿)")
    chk(q["gate"]["pass"], "artifact gate", "; ".join(q["gate"]["fails"][:2]) or "all invariants hold")
    return v


def render_md(q: dict, base: dict | None) -> str:
    f, c, d = q["freshness"], q["coverage"], q["duplication"]
    L: list[str] = []
    L.append(f"# 데이터 품질 리포트 — {q['as_of'][:10]}")
    L.append("\n생성: `pipelines/quality_report.py` · 원본(Neo4j) 직접 측정 · 서술적 관측만\n")

    L.append("## 판정\n")
    L.append("| 상태 | 항목 | 비고 |")
    L.append("|---|---|---|")
    for status, name, note in verdicts(q):
        icon = "🟢" if status == "PASS" else "🟠"
        L.append(f"| {icon} {status} | {name} | {note} |")

    L.append("\n## 신선도 (원본)\n")
    L.append(f"- MacroIndicator: {f['macro_n']}개, 최대 나이 {f['macro_max_age_d']}일"
             + (f" — **stale: {', '.join(f['macro_stale'])}**" if f['macro_stale'] else " (전부 신선)"))
    L.append(f"- PriceSeries: {f['price_n']}개 중 {f['price_fresh_pct']}%가 {MACRO_FRESH_DAYS}일 이내")
    L.append(f"- 뉴스 Claim {f['news_claims']:,}개 · 최신 knowledge {f['news_knowledge_age_d']}일 전 "
             f"· 최신 event {f['news_event_age_d']}일 전")
    L.append(f"- AnalysisResult 최신 as_of: {f['analysis_latest_as_of']} · ThemeDay 최신: {f['themeday_latest']}")

    L.append("\n## 커버리지 (유니버스 내)\n")
    L.append(f"- 유니버스 발행사 {c['universe_issuers']}개 기준: 뉴스 {c['news_pct']}% · "
             f"가격 {c['price_pct']}% · 52주위치 {c['pos52w_pct']}% · 섹터 {c['sector_pct']}%")

    L.append("\n## 중복\n")
    L.append(f"- 뉴스 중복률 {d['ratio']} (목표 ~1.0)")

    p = q.get("published", {})
    if "error" not in p:
        L.append("\n## 배포물 건강 (loop_metrics)\n")
        L.append(f"- graph {p.get('graph_issuers')} · themes {p.get('themes_nodes')} · "
                 f"emergent {p.get('emergent_terms')} · stance 중립 {p.get('stance_neut_pct')}% "
                 f"(강세 {p.get('stance_bull_pct')}% / 약세 {p.get('stance_bear_pct')}%)")
        L.append(f"- emergent 허브: {', '.join(p.get('emergent_top_hubs', [])[:8])}")

    if base:
        cur, prev = _flatten(q), _flatten(base)
        moved = [(k, prev[k], cur[k]) for k in sorted(cur.keys() & prev.keys())
                 if abs(cur[k] - prev[k]) > 1e-9]
        L.append(f"\n## 베이스라인 대비 변화 ({base.get('as_of', '?')[:10]} → {q['as_of'][:10]})\n")
        if moved:
            L.append("| 지표 | 이전 | 현재 |")
            L.append("|---|---|---|")
            for k, a, b in moved:
                L.append(f"| {k} | {a} | {b} |")
        else:
            L.append("- 변화 없음")
    else:
        L.append("\n*(베이스라인 없음 — 이번 값이 베이스라인으로 저장됨)*")
    L.append("")
    return "\n".join(L)


def main() -> None:
    repo = make_repo(cfg)
    if not hasattr(repo, "_read"):
        print("[quality] needs the Neo4j backend (SKG_STORAGE_BACKEND=neo4j)")
        return
    as_of = cfg.AS_OF_NOW
    q = collect(repo, as_of)
    repo.close()

    base = None
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))

    cfg.OUT.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(q, base), encoding="utf-8")

    if base is None or "--rebase" in sys.argv:
        BASELINE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[quality] baseline {'re-set' if base else 'created'} -> {BASELINE}")

    for status, name, note in verdicts(q):
        print(f"  {status:4} {name:24} {note}")
    print(f"[quality] report -> {OUT_MD}")


if __name__ == "__main__":
    main()
