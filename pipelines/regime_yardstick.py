"""regime_yardstick.py — market regime as same/cross-sector residual-corr distributions.

    SKG_STORAGE_BACKEND=neo4j python pipelines/regime_yardstick.py

Promotes the validated comovement computation (same-sector μ vs cross-sector μ of residual
pair correlations) from a one-off report into a STABILITY-GATED market-state yardstick:

  - cross-sector μ near 0  → sector-differentiated tape (stocks move on their own stories)
  - cross-sector μ elevated → macro-driven tape (everything moves together, risk-on/off)
  - the same-sector μ is the scale reference that makes the cross number readable

STABILITY GATE (the lead/lag lesson — never ship a number that flips when the window moves):
the ordering μ_same > μ_cross must hold on the FULL window AND on both split halves, in every
market, and each half must retain a meaningful share of the full-window gap. If the gate
fails, the honest output is "unstable — not shipped", which is a NORMAL exit, not an error.

READ-ONLY: writes out/regime_report.md + out/regime_yardstick.json (candidate data for a
dashboard block; deploying it is a separate, gated decision). Descriptive only — the report
never says what WILL happen, only how the tape HAS been moving.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import json
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config as cfg
from skg.database import make_repo
from skg.analyze.comovement import (dominant_cohort, residualize, sector_distributions,
                                    simple_returns)

MIN_NAMES = 40        # a distribution over fewer issuers is anecdote, not a yardstick
HALF_MIN_N = 40       # pair-corr min length inside a split half (~44 returns)
GAP_RETAIN = 0.35     # each half must keep >= this share of the full-window gap

MARKETS = {
    "KR": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'DART' "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, p.recent_closes_json AS c, p.window_end AS we, s.name AS sec"),
    "US": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'CIK' "
           "AND i.index_membership IS NOT NULL "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, p.recent_closes_json AS c, p.window_end AS we, s.name AS sec"),
}


def _dist_stats(vals: list[float]) -> dict:
    return {"mu": round(statistics.mean(vals), 4), "sd": round(statistics.pstdev(vals), 4),
            "n": len(vals)} if vals else {"mu": None, "sd": None, "n": 0}


def _window_dists(names: list[str], R: dict[str, list[float]], SEC: dict[str, str],
                  t0: int, t1: int, min_n: int) -> dict:
    """Residualize INSIDE the [t0:t1) slice (beta drifts across time), then pair-corr."""
    L = t1 - t0
    sliced = {n: R[n][t0:t1] for n in names}
    mkt = [statistics.mean(sliced[n][t] for n in names) for t in range(L)]
    mres = {n: residualize(sliced[n], mkt, L) for n in names}
    same, cross = sector_distributions(names, mres, SEC, min_n=min_n)
    s, c = _dist_stats(same), _dist_stats(cross)
    s["gap"] = round((s["mu"] or 0) - (c["mu"] or 0), 4) if s["n"] and c["n"] else None
    return {"same": s, "cross": c, "days": L}


def analyze_market(repo, label: str, cypher: str) -> dict | None:
    rows = repo._read(cypher)
    end_day, S, SEC = dominant_cohort(rows, want_len=cfg.PRICE_WINDOW_DAYS)
    if len(S) < MIN_NAMES:
        return {"market": label, "skipped": f"aligned cohort too small ({len(S)})"}
    names = sorted(S)
    R = {n: simple_returns(S[n]) for n in names}
    L = min(len(v) for v in R.values())
    R = {n: v[-L:] for n, v in R.items()}
    half = L // 2

    full = _window_dists(names, R, SEC, 0, L, min_n=50)
    h1 = _window_dists(names, R, SEC, 0, half, min_n=HALF_MIN_N)
    h2 = _window_dists(names, R, SEC, half, L, min_n=HALF_MIN_N)

    gaps = [w["same"]["gap"] for w in (full, h1, h2)]
    ordered = all(g is not None and g > 0 for g in gaps)
    retained = (ordered and full["same"]["gap"] and
                all(w["same"]["gap"] >= GAP_RETAIN * full["same"]["gap"] for w in (h1, h2)))
    return {
        "market": label, "end_day": end_day, "issuers": len(names), "returns_days": L,
        "full": full, "half1": h1, "half2": h2,
        "stable": bool(ordered and retained),
        "gate": {"ordering_all_windows": ordered, "halves_retain_gap": bool(retained),
                 "gap_full": full["same"]["gap"], "gap_h1": h1["same"]["gap"],
                 "gap_h2": h2["same"]["gap"]},
    }


def render(results: list[dict], as_of: str) -> str:
    L: list[str] = []
    L.append(f"# 시장 응집도(레짐) 야드스틱 — {as_of[:10]}")
    L.append("\n같은-섹터 vs 다른-섹터 residual 상관 분포. **서술 전용** — 시장이 어떻게 움직여"
             "왔는지의 관측이지 예측이 아님. 안정성 게이트(전체창+반분창 순서 유지) 통과분만 승격.\n")
    for r in results:
        if r.get("skipped"):
            L.append(f"## {r['market']} — 건너뜀 ({r['skipped']})\n")
            continue
        g = r["gate"]
        L.append(f"## {r['market']} — {'🟢 안정 (승격 가능)' if r['stable'] else '🟠 불안정 (미출시)'}\n")
        L.append(f"*{r['issuers']}개 종목 · {r['returns_days']}일 수익률 · 정렬 {r['end_day']}*\n")
        L.append("| 창 | 같은-섹터 μ (σ, n) | 다른-섹터 μ (σ, n) | 격차 |")
        L.append("|---|---|---|---|")
        for name, w in (("전체", r["full"]), ("전반", r["half1"]), ("후반", r["half2"])):
            s, c = w["same"], w["cross"]
            L.append(f"| {name} ({w['days']}d) | {s['mu']:+.3f} ({s['sd']:.3f}, {s['n']:,}) "
                     f"| {c['mu']:+.3f} ({c['sd']:.3f}, {c['n']:,}) | {s['gap']:+.3f} |")
        L.append("")
        if r["stable"]:
            cross_mu = r["full"]["cross"]["mu"]
            tape = ("섹터 분화장 — 다른-섹터 동조가 ~0, 종목이 각자의 재료로 움직임"
                    if abs(cross_mu) < 0.05 else
                    "매크로 일제동조 성향 — 다른-섹터끼리도 함께 움직임 (risk-on/off 국면)")
            L.append(f"- 관측: {tape} (다른-섹터 μ={cross_mu:+.3f})")
        else:
            L.append(f"- 게이트 상세: 순서유지={g['ordering_all_windows']} · "
                     f"반분창 격차유지={g['halves_retain_gap']} "
                     f"(전체 {g['gap_full']} vs 전반 {g['gap_h1']} / 후반 {g['gap_h2']})")
            L.append("- 창을 옮기면 뒤집히는 수치는 출시하지 않음 (리드/래그 교훈).")
        L.append("")
    L.append("*방법: 일별 수익률에서 코호트 동일가중 지수 베타 제거 → 쌍별 residual 상관 → "
             "섹터 동일/상이로 분리한 분포. 상관≠인과, 신호 아님.*\n")
    return "\n".join(L)


def main() -> None:
    repo = make_repo(cfg)
    if not hasattr(repo, "_read"):
        print("[regime] needs the Neo4j backend (SKG_STORAGE_BACKEND=neo4j)")
        return
    as_of = cfg.AS_OF_NOW
    results = [analyze_market(repo, m, q) for m, q in MARKETS.items()]
    repo.close()

    cfg.OUT.mkdir(parents=True, exist_ok=True)
    (cfg.OUT / "regime_yardstick.json").write_text(
        json.dumps({"as_of": as_of, "markets": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (cfg.OUT / "regime_report.md").write_text(render(results, as_of), encoding="utf-8")

    for r in results:
        if r.get("skipped"):
            print(f"[regime] {r['market']}: skipped ({r['skipped']})")
        else:
            print(f"[regime] {r['market']}: full gap {r['gate']['gap_full']:+.3f} "
                  f"(h1 {r['gate']['gap_h1']:+.3f} / h2 {r['gate']['gap_h2']:+.3f}) "
                  f"-> {'STABLE' if r['stable'] else 'UNSTABLE (not shipped)'}")
    print(f"[regime] report -> {cfg.OUT / 'regime_report.md'}")


if __name__ == "__main__":
    main()
