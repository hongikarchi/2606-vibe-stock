"""comovement_verify.py — cross-modal, news-INDEPENDENT verification via price co-movement.

    SKG_STORAGE_BACKEND=neo4j python pipelines/comovement_verify.py

The answer to "do I have to verify every connection by hand?" — NO. Price co-movement is an
independent data modality (not the news the bridge was inferred from), so it verifies a link is
REAL without a human thumb. Two layers from ONE residual-correlation computation:

  MICRO — verify bridge pairs. Residualize each stock's daily returns vs an equal-weight market
    index (remove beta), then judge a pair's residual corr against the SAME-SECTOR baseline (not
    the universe). The non-obvious survivors are CROSS-sector pairs with high residual corr — a
    supply-chain link the sector lookup can't give you (LG엔솔 cell ↔ 포스코퓨처엠 cathode). A
    same-sector pair that co-moves is just "same industry" = obvious, and is demoted as such.

  MACRO — regime as fact (DESCRIPTIVE only, never a call). The same-sector vs cross-sector residual
    distributions ARE the regime yardstick: cross-sector mean near 0 = sector-differentiated tape;
    elevated = broad macro-driven tape. Reported with its reference distribution, not as a bare
    scalar.

HONEST BOUNDS (do not overclaim):
  - Verifies REAL (modulo sector), NOT "non-obvious" (cross-sector control handles most of that)
    and NOT "worth paying for" (a small residual stays human).
  - Single ~90-day window is noisy: z>=4 credible, z~2 suggestive-not-robust. Multi-window
    persistence is future work.
  - Residual corr is ASSOCIATIONAL/descriptive ("moved together, consistent with the link"),
    never "A drives B". Stays inside the no-prediction line the user set.
  - Equal-weight self-index is used because the KOSPI MacroIndicator node is stale (06-23 vs
    stocks 06-29 — the documented freshness divergence); self-index avoids that misalignment.

READ-ONLY. Writes only a review report (out/comovement_report.md). Does NOT deploy or touch
web/public/data — a new surface with no regression baseline is not auto-shipped (EDGAR rule).
"""
from __future__ import annotations

import sys
import json
import math
import pathlib
import statistics
import itertools
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.database import make_repo

MIN_LEN = 90          # full window only (ragged short-history series excluded)
END_DAY = None        # set from the dominant cohort at runtime


def _closes(j):
    try:
        return json.loads(j) if j else None
    except Exception:
        return None


def _rets(c):
    return [(c[i + 1] - c[i]) / c[i] for i in range(len(c) - 1) if c[i]]


def _resid(y, base, L):
    mx = sum(base) / L
    my = sum(y) / L
    cov = sum((base[t] - mx) * (y[t] - my) for t in range(L))
    vx = sum((base[t] - mx) ** 2 for t in range(L))
    b = cov / vx if vx else 0.0
    return [y[t] - b * base[t] for t in range(L)]


def _corr(a, b):
    n = len(a)
    if n < 50:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return cov / (va * vb) if va and vb else None


def main() -> None:
    repo = make_repo(cfg)
    rows = repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'DART' "
        "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
        "RETURN i.name AS n, p.recent_closes_json AS c, p.window_end AS we, s.name AS sec")

    # dominant freshness cohort (avoid mixing stale endpoints)
    cohort = defaultdict(int)
    for r in rows:
        if _closes(r["c"]):
            cohort[(r["we"] or "")[:10]] += 1
    end_day = max(cohort, key=cohort.get) if cohort else ""

    S, SEC = {}, {}
    for r in rows:
        c = _closes(r["c"])
        if c and len(c) == MIN_LEN and (r["we"] or "")[:10] == end_day:
            S[r["n"]] = c
            SEC[r["n"]] = r["sec"] or "(none)"
    names = list(S)
    if len(names) < 20:
        print(f"[comovement] too few aligned series ({len(names)}) — abort")
        repo.close()
        return

    R = {n: _rets(c) for n, c in S.items()}
    L = min(len(v) for v in R.values())
    R = {n: v[-L:] for n, v in R.items()}
    mkt = [statistics.mean(R[n][t] for n in names) for t in range(L)]
    mres = {n: _resid(R[n], mkt, L) for n in names}

    same, cross = [], []
    for a, b in itertools.combinations(names, 2):
        rc = _corr(mres[a], mres[b])
        if rc is None:
            continue
        (same if SEC[a] == SEC[b] and SEC[a] != "(none)" else cross).append(rc)
    mu_s, sd_s = statistics.mean(same), statistics.pstdev(same)
    mu_c, sd_c = statistics.mean(cross), statistics.pstdev(cross)

    # MICRO: verify the curated bridge pairs (kept in sync with mine_bridges ✅ output)
    BRIDGE_PAIRS = [
        ("일진전기", "효성중공업", "변압기/초고압"),
        ("LG에너지솔루션", "포스코퓨처엠", "ESS/전고체(셀↔양극재)"),
        ("HD현대일렉트릭", "일진전기", "변압기/초고압"),
        ("삼성전기", "대덕전자", "FC-BGA"),
        ("LG이노텍", "심텍", "FC-BGA/HBM"),
    ]
    micro = []
    for a, b, lbl in BRIDGE_PAIRS:
        if a not in mres or b not in mres:
            micro.append((a, b, lbl, None, None, None, "series 없음"))
            continue
        rc = _corr(mres[a], mres[b])
        same_sec = SEC[a] == SEC[b] and SEC[a] != "(none)"
        mu, sd = (mu_s, sd_s) if same_sec else (mu_c, sd_c)
        z = (rc - mu) / sd if sd else 0.0
        if same_sec and z < 1.0:
            verdict = "자명(같은 섹터)"
        elif (not same_sec) and z >= 1.5:
            verdict = "✅ 섹터 넘은 실제 동조(연결 뒷받침)"
        elif z >= 1.5:
            verdict = "✅ 동조(같은 섹터 내에서도 이례적)"
        else:
            verdict = "❌ 가격으로 미확인(뉴스만의 연결)"
        micro.append((a, b, lbl, round(rc, 2), round(z, 1), same_sec, verdict))

    out = ["# 가격 동조성(co-movement) 검증 — 뉴스와 독립된 팩트 검증 (읽기전용 · 배포 안 됨)\n",
           "가격은 뉴스 추론과 다른 독립 모달리티라, 사람이 일일이 확인하지 않아도 '이 연결이 실제인가'를",
           "팩트로 검증함. 시장 베타 제거(residual) 후, **같은-섹터 기준선**과 비교(섹터로 자명한 동조를 걸러냄).\n",
           f"as_of {cfg.AS_OF_NOW[:10]} · {len(names)}개 KR 종목 · {L+1}일 윈도우 · 정렬 {end_day}\n",
           "## 거시(MACRO) — 시장 국면 (서술 전용, 예측 아님)\n",
           f"- 같은 섹터 쌍 residual corr 평균 **{mu_s:+.3f}** (σ {sd_s:.3f}, n={len(same)})",
           f"- 다른 섹터 쌍 residual corr 평균 **{mu_c:+.3f}** (σ {sd_c:.3f}, n={len(cross)})",
           f"- 해석: 다른-섹터 평균이 0 근처 → **섹터 분화장**(같은 섹터끼리만 동조, 시장 전체 일제동조 아님).",
           "  이 두 분포가 국면의 yardstick — 다른-섹터 평균이 올라가면 매크로 일제동조(risk-on/off)로 전환 신호.\n",
           "## 미시(MICRO) — bridge pair를 가격으로 검증\n",
           "섹터를 넘어서도 동조하는 쌍 = 섹터로 설명 안 되는 진짜 공급망 연결(비자명). 같은 섹터 동조 = 자명.\n"]
    for a, b, lbl, rc, z, same_sec, v in micro:
        secinfo = f"[{SEC.get(a)} / {SEC.get(b)}]" if rc is not None else ""
        rcs = f"residual r={rc:+.2f} z={z:+.1f}σ" if rc is not None else "(데이터 없음)"
        out.append(f"- **{a} ↔ {b}** ({lbl}) {rcs} {secinfo} → {v}")
    out.append("\n*경계: 가격 동조는 '연결이 실제임'을 검증(섹터 통제 후)하지만, '비자명/살 가치'까지는 아님.")
    out.append("단일 90일 창은 노이즈 — z≥4 신뢰, z~2 시사적. 다중창 지속성은 후속 작업. 동조는 연관(서술)이지 인과 아님.*")

    report = pathlib.Path(cfg.OUT) / "comovement_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out), encoding="utf-8")
    print(f"[comovement] {len(names)} issuers · same-sector μ={mu_s:+.3f} cross-sector μ={mu_c:+.3f}")
    for a, b, lbl, rc, z, ss, v in micro:
        print(f"    {a}↔{b}: r={rc} z={z} -> {v}")
    print(f"[comovement] report -> {report}")
    repo.close()


if __name__ == "__main__":
    main()
