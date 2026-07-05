"""flow_clusters.py — data-driven market-flow clusters from the residual-corr matrix.

    SKG_STORAGE_BACKEND=neo4j python pipelines/flow_clusters.py

The gazetteer themes say what the NEWS connects; this asks what the MONEY connects: block-
structure in the residual correlation matrix (market beta removed) = groups of stocks that
move together beyond the index — the data's own version of "market flows". Each stock gets a
LOADING (corr to its cluster's centroid) = how tightly it belongs.

Method (deterministic, no randomness): pairwise residual corr → distance 1-corr → average-
linkage hierarchical clustering (scipy, deterministic) → cut chosen by max mean silhouette
over a fixed threshold grid.

QUALITY GATES (honest-reporting rules):
  - split-half stability: cluster the two halves of the window independently; Adjusted Rand
    Index between the halves must clear a floor, else the structure is noise → report
    "unstable, not shipped" and stop (a NORMAL exit).
  - contrast, not blend: clusters are compared against KSIC/SIC sectors (purity) and the
    gazetteer theme tags — where they AGREE the sector story is confirmed; where a cluster
    CROSSES sectors it is the interesting, non-obvious flow (same logic as bridge verify).

READ-ONLY: writes out/flow_clusters.md + out/flow_clusters.json. Never deployed by itself.
Descriptive only — co-movement is association, not causation, not a signal.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import json
import statistics
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config as cfg
from skg.database import make_repo
from skg.analyze.comovement import (dominant_cohort, pearson, residualize, simple_returns)

MIN_NAMES = 40
THRESH_GRID = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]   # distance cut candidates
MIN_CLUSTER = 3          # singletons/pairs are not "flows"
ARI_FLOOR = 0.25         # split-half floor: below this the block structure is noise
HALF_MIN_N = 40

MARKETS = {
    "KR": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'DART' "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, i.issuer_id AS iid, p.recent_closes_json AS c, "
           "p.window_end AS we, s.name AS sec"),
    "US": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'CIK' "
           "AND i.index_membership IS NOT NULL "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, i.issuer_id AS iid, p.recent_closes_json AS c, "
           "p.window_end AS we, s.name AS sec"),
}


# --------------------------------------------------------------- clustering (deterministic)
def _residuals(names, R, t0, t1):
    L = t1 - t0
    sliced = {n: R[n][t0:t1] for n in names}
    mkt = [statistics.mean(sliced[n][t] for n in names) for t in range(L)]
    return {n: residualize(sliced[n], mkt, L) for n in names}


def _corr_matrix(names, mres, min_n):
    """np.corrcoef over the residual matrix — same value as pairwise pearson (all series
    share one aligned length, so min_n is a window gate, not a per-pair one)."""
    import numpy as np
    X = np.array([mres[n] for n in names])
    if X.shape[1] < min_n:
        raise ValueError(f"window too short ({X.shape[1]} < {min_n})")
    M = np.nan_to_num(np.corrcoef(X), nan=0.0)   # flat series -> nan -> 0 (matches pearson)
    np.fill_diagonal(M, 1.0)
    return M


def _cluster(names, M, thresh):
    """Average-linkage agglomerative on distance 1-corr, cut at `thresh`. Deterministic."""
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    D = np.clip(1.0 - M, 0.0, 2.0)
    np.fill_diagonal(D, 0.0)
    Z = linkage(squareform(D, checks=False), method="average")
    return fcluster(Z, t=thresh, criterion="distance")


def _silhouette(labels, M) -> float:
    """Mean silhouette on the precomputed distance (1-corr), clustered points only."""
    import numpy as np
    D = 1.0 - M
    groups = defaultdict(list)
    for i, l in enumerate(labels):
        groups[l].append(i)
    vals = []
    for i, l in enumerate(labels):
        own = [j for j in groups[l] if j != i]
        if not own:
            continue
        a = float(np.mean([D[i, j] for j in own]))
        bs = [float(np.mean([D[i, j] for j in members]))
              for g, members in groups.items() if g != l and members]
        if not bs:
            continue
        b = min(bs)
        vals.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return round(statistics.mean(vals), 4) if vals else 0.0


def _ari(a: list[int], b: list[int]) -> float:
    """Adjusted Rand Index, pure python (deterministic)."""
    from math import comb
    n = len(a)
    ct: dict[tuple[int, int], int] = Counter(zip(a, b))
    rows, cols = Counter(a), Counter(b)
    sum_ij = sum(comb(v, 2) for v in ct.values())
    sum_a = sum(comb(v, 2) for v in rows.values())
    sum_b = sum(comb(v, 2) for v in cols.values())
    total = comb(n, 2)
    exp = sum_a * sum_b / total if total else 0.0
    mx = (sum_a + sum_b) / 2
    return round((sum_ij - exp) / (mx - exp), 4) if mx != exp else 0.0


def _pick_cut(names, M):
    """Choose the distance cut by max mean silhouette over the fixed grid (deterministic;
    ties broken by the smaller threshold = tighter clusters)."""
    best = None
    for t in THRESH_GRID:
        labels = _cluster(names, M, t)
        sizes = Counter(labels)
        n_real = sum(1 for _, s in sizes.items() if s >= MIN_CLUSTER)
        if n_real < 2:
            continue
        sil = _silhouette(labels, M)
        cand = (sil, -t, labels, n_real)
        if best is None or cand[:2] > best[:2]:
            best = cand
    return best  # (sil, -t, labels, n_real) or None


# --------------------------------------------------------------- theme/sector contrast
def _theme_tags(repo, iids: list[str]) -> dict[str, list[str]]:
    rows = repo._read(
        "MATCH (t:Theme)-[r:MENTIONED_WITH]->(i:Issuer) WHERE i.issuer_id IN $iids "
        "RETURN i.issuer_id AS iid, t.theme_id AS tid, r.weight AS w", iids=iids)
    by: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in rows:
        by[r["iid"]].append((r["w"] or 0, r["tid"]))
    return {iid: [t for _, t in sorted(pairs, reverse=True)[:3]] for iid, pairs in by.items()}


def analyze_market(repo, label, cypher) -> dict:
    rows = repo._read(cypher)
    end_day, S, SEC = dominant_cohort(rows, want_len=cfg.PRICE_WINDOW_DAYS)
    iid_of = {r["n"]: r["iid"] for r in rows}
    if len(S) < MIN_NAMES:
        return {"market": label, "skipped": f"aligned cohort too small ({len(S)})"}
    names = sorted(S)
    R = {n: simple_returns(S[n]) for n in names}
    L = min(len(v) for v in R.values())
    R = {n: v[-L:] for n, v in R.items()}
    half = L // 2

    # full-window clustering (the candidate structure)
    mres = _residuals(names, R, 0, L)
    M = _corr_matrix(names, mres, min_n=50)
    picked = _pick_cut(names, M)
    if picked is None:
        return {"market": label, "skipped": "no cut produces >=2 real clusters"}
    sil, neg_t, labels, n_real = picked

    # split-half stability (cluster each half INDEPENDENTLY, same cut)
    lab_h = []
    for t0, t1 in ((0, half), (half, L)):
        mres_h = _residuals(names, R, t0, t1)
        M_h = _corr_matrix(names, mres_h, min_n=HALF_MIN_N)
        lab_h.append(list(_cluster(names, M_h, -neg_t)))
    ari = _ari(lab_h[0], lab_h[1])

    # assemble clusters (members, loading = corr to centroid, sector purity, themes)
    import numpy as np
    groups = defaultdict(list)
    for n, l in zip(names, labels):
        groups[l].append(n)
    clusters = []
    tags = _theme_tags(repo, [iid_of[n] for n in names])
    for l, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < MIN_CLUSTER:
            continue
        cent = [statistics.mean(mres[m][t] for m in members) for t in range(L)]
        loads = sorted(((m, round(pearson(mres[m], cent) or 0.0, 2)) for m in members),
                       key=lambda x: -x[1])
        secs = Counter(SEC[m] for m in members)
        top_sec, top_n = secs.most_common(1)[0]
        themes = Counter(t for m in members for t in tags.get(iid_of[m], []))
        clusters.append({
            "size": len(members),
            "sector_purity": round(top_n / len(members), 2),
            "top_sector": top_sec,
            "cross_sector": top_n / len(members) < 0.6,
            "themes": [t for t, _ in themes.most_common(3)],
            "members": [{"name": m, "loading": w, "sector": SEC[m]} for m, w in loads],
        })
    return {"market": label, "end_day": end_day, "issuers": len(names), "returns_days": L,
            "cut": -neg_t, "silhouette": sil, "clusters_n": len(clusters),
            "ari_split_half": ari, "stable": ari >= ARI_FLOOR, "clusters": clusters}


def render(results, as_of) -> str:
    L: list[str] = []
    L.append(f"# 시장 흐름 클러스터 (데이터 기반) — {as_of[:10]}")
    L.append("\n뉴스 테마(키워드 기반)와 독립적으로, **가격 residual 상관의 블록 구조**가 말하는 "
             "자금 흐름 군집. 서술 전용 · 상관≠인과 · 신호 아님.\n")
    for r in results:
        if r.get("skipped"):
            L.append(f"## {r['market']} — 건너뜀 ({r['skipped']})\n")
            continue
        L.append(f"## {r['market']} — {'🟢 안정' if r['stable'] else '🟠 불안정 (구조=노이즈, 미출시)'} "
                 f"(split-half ARI {r['ari_split_half']:+.2f}, floor {ARI_FLOOR})\n")
        L.append(f"*{r['issuers']}개 종목 · cut {r['cut']} · silhouette {r['silhouette']} · "
                 f"군집 {r['clusters_n']}개 · 정렬 {r['end_day']}*\n")
        if not r["stable"]:
            L.append("- 반분창에서 군집이 재현되지 않음 — 이 창의 블록 구조는 출시하지 않음.\n")
            continue
        for i, c in enumerate(r["clusters"], 1):
            kind = "⚡ 섹터 교차(비자명)" if c["cross_sector"] else f"섹터 응집({c['top_sector']})"
            th = f" · 테마: {', '.join(c['themes'])}" if c["themes"] else ""
            L.append(f"### {r['market']}-{i} [{c['size']}종목] {kind} (순도 {c['sector_purity']}){th}\n")
            mm = ", ".join(f"{m['name']}({m['loading']:+.2f})" for m in c["members"][:10])
            more = f" 외 {c['size']-10}" if c["size"] > 10 else ""
            L.append(f"- {mm}{more}")
            L.append("")
    L.append("*방법: 동일가중 지수 베타 제거 → 쌍별 residual 상관 → 평균연결 계층 군집(결정론) → "
             "silhouette로 절단 선택 → 반분창 ARI 안정성 게이트. loading = 군집 중심과의 상관.*\n")
    return "\n".join(L)


def main() -> None:
    repo = make_repo(cfg)
    if not hasattr(repo, "_read"):
        print("[flow] needs the Neo4j backend (SKG_STORAGE_BACKEND=neo4j)")
        return
    as_of = cfg.AS_OF_NOW
    results = [analyze_market(repo, m, q) for m, q in MARKETS.items()]
    repo.close()

    cfg.OUT.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"as_of": as_of, "markets": results}, ensure_ascii=False, indent=2)
    (cfg.OUT / "flow_clusters.json").write_text(payload, encoding="utf-8")
    (cfg.OUT / "flow_clusters.md").write_text(render(results, as_of), encoding="utf-8")
    # as_of별 아카이브 — 한 달 뒤 첫 창간 ARI(클러스터 지속성) 측정의 전제 (감사 해금 #1)
    hist = cfg.ROOT / "data" / "history" / "flow"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"flow_{as_of[:10]}.json").write_text(payload, encoding="utf-8")
    for r in results:
        if r.get("skipped"):
            print(f"[flow] {r['market']}: skipped ({r['skipped']})")
        else:
            print(f"[flow] {r['market']}: {r['clusters_n']} clusters, sil {r['silhouette']}, "
                  f"ARI {r['ari_split_half']} -> {'STABLE' if r['stable'] else 'UNSTABLE (not shipped)'}")
    print(f"[flow] report -> {cfg.OUT / 'flow_clusters.md'}")


if __name__ == "__main__":
    main()
