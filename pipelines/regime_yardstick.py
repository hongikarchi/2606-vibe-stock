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


def _reference_windows(market: str, want_len: int = 90, stride: int = 21) -> list[dict]:
    """Rolling-window reference distribution from the one-time 3y backfill
    (data/history/px_3y/<market>.json.gz, pipelines/backfill_history.py). Each window:
    same/cross-sector residual-corr gap + cross-μ — the history that lets the CURRENT
    window be placed as a percentile instead of a bare n=1 scalar.
    SURVIVORSHIP CAVEAT: backfill covers today's universe; fine for dispersion structure,
    never for return claims."""
    import gzip
    p = cfg.ROOT / "data" / "history" / "px_3y" / f"{market}.json.gz"
    if not p.exists():
        return []
    import numpy as np
    data = json.loads(gzip.open(p, "rt", encoding="utf-8").read())
    tickers = data["tickers"]
    all_dates = sorted({d for v in tickers.values() for d in v["dates"]})
    if len(all_dates) < want_len + stride:
        return []
    out = []
    for end_i in range(want_len, len(all_dates), stride):
        end_date = all_dates[end_i]
        names, rows, secs = [], [], []
        for n, v in sorted(tickers.items()):
            ds = v["dates"]
            # last want_len bars ending at/before end_date, ticker must trade near the end
            k = len([d for d in ds if d <= end_date])
            if k < want_len or (ds[k - 1] < all_dates[max(0, end_i - 5)]):
                continue
            closes = v["closes"][k - want_len:k]
            rows.append(closes)
            names.append(n)
            secs.append(v["sector"])
        if len(names) < MIN_NAMES:
            continue
        X = np.diff(np.array(rows), axis=1) / np.array(rows)[:, :-1]
        mkt = X.mean(axis=0)
        beta = ((X - X.mean(axis=1, keepdims=True)) @ (mkt - mkt.mean())) / \
               ((mkt - mkt.mean()) @ (mkt - mkt.mean()))
        resid = X - np.outer(beta, mkt)
        C = np.corrcoef(resid)
        sec_arr = np.array(secs)
        same_mask = (sec_arr[:, None] == sec_arr[None, :]) & (sec_arr[:, None] != "(none)")
        iu = np.triu_indices(len(names), k=1)
        same_vals = C[iu][same_mask[iu]]
        cross_vals = C[iu][~same_mask[iu]]
        if not len(same_vals) or not len(cross_vals):
            continue
        out.append({"end": end_date, "n": len(names),
                    "gap": round(float(same_vals.mean() - cross_vals.mean()), 4),
                    "cross_mu": round(float(cross_vals.mean()), 4)})
    return out


def _percentile(vals: list[float], x: float) -> float:
    if not vals:
        return 0.0
    return round(100 * sum(1 for v in vals if v <= x) / len(vals), 1)


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

    # 역사 참조 (3y 백필이 있으면): 현재 창의 gap / cross-μ 를 역사 분포의 백분위로
    ref = _reference_windows(label)
    hist = None
    if ref:
        hist = {
            "windows": len(ref), "span": f"{ref[0]['end']} ~ {ref[-1]['end']}",
            "gap_pct": _percentile([r["gap"] for r in ref], full["same"]["gap"]),
            "cross_mu_pct": _percentile([r["cross_mu"] for r in ref], full["cross"]["mu"]),
            "gap_hist_med": round(statistics.median(r["gap"] for r in ref), 4),
            "cross_hist_med": round(statistics.median(r["cross_mu"] for r in ref), 4),
        }

    return {
        "market": label, "end_day": end_day, "issuers": len(names), "returns_days": L,
        "full": full, "half1": h1, "half2": h2,
        "stable": bool(ordered and retained),
        "history": hist,
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
            h = r.get("history")
            if h:
                L.append(f"- **역사 대비** (3년 롤링 {h['windows']}개 창, {h['span']}): "
                         f"현재 응집 격차는 역사 분포의 **{h['gap_pct']}백분위** "
                         f"(역사 중앙값 {h['gap_hist_med']:+.3f}), 다른-섹터 동조는 "
                         f"{h['cross_mu_pct']}백분위 — 현 우주 기준 백필이라 생존편향 있음(구조 비교용).")
            else:
                L.append("- 역사 참조 없음 — `pipelines/backfill_history.py` 1회 실행 시 "
                         "'지금이 이례적인가'가 백분위로 표시됨.")
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
    payload = json.dumps({"as_of": as_of, "markets": results}, ensure_ascii=False, indent=2)
    (cfg.OUT / "regime_yardstick.json").write_text(payload, encoding="utf-8")
    (cfg.OUT / "regime_report.md").write_text(render(results, as_of), encoding="utf-8")
    # as_of별 아카이브 — 덮어쓰기만 하면 창 간 비교가 영원히 n=1 (충분성 감사 해금 #1)
    hist = cfg.ROOT / "data" / "history" / "regime"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"regime_{as_of[:10]}.json").write_text(payload, encoding="utf-8")

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
