"""comovement — shared residual co-movement primitives (pure, deterministic, stdlib).

Used by pipelines/comovement_verify.py (bridge verification), regime_yardstick.py (macro
regime as same/cross-sector residual distributions) and flow_clusters.py (data-driven
market-flow clustering). All DESCRIPTIVE: residual correlation says "moved together after
removing market beta", never causation, never a signal.

The residualization is vs an EQUAL-WEIGHT self-index of the cohort (not an index node) —
avoids any freshness misalignment between :PriceSeries and :MacroIndicator windows.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict


def closes_of(j: str | None) -> list[float] | None:
    try:
        return json.loads(j) if j else None
    except (ValueError, TypeError):
        return None


def simple_returns(closes: list[float]) -> list[float]:
    return [(closes[i + 1] - closes[i]) / closes[i]
            for i in range(len(closes) - 1) if closes[i]]


def residualize(y: list[float], base: list[float], L: int) -> list[float]:
    """OLS-remove the cohort (market) component from one return series."""
    mx = sum(base) / L
    my = sum(y) / L
    cov = sum((base[t] - mx) * (y[t] - my) for t in range(L))
    vx = sum((base[t] - mx) ** 2 for t in range(L))
    b = cov / vx if vx else 0.0
    return [y[t] - b * base[t] for t in range(L)]


def pearson(a: list[float], b: list[float], min_n: int = 50) -> float | None:
    n = len(a)
    if n < min_n:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else None


def dominant_cohort(rows, closes_key: str = "c", end_key: str = "we",
                    want_len: int = 90) -> tuple[str, dict[str, list[float]], dict[str, str]]:
    """Pick the dominant window-end day and return (end_day, {name: closes}, {name: sector}).
    Mixing stale endpoints would misalign returns; the cohort keeps only series that end on
    the SAME day with the full window length."""
    cohort: dict[str, int] = defaultdict(int)
    for r in rows:
        if closes_of(r[closes_key]):
            cohort[(r[end_key] or "")[:10]] += 1
    end_day = max(cohort, key=cohort.get) if cohort else ""
    S: dict[str, list[float]] = {}
    SEC: dict[str, str] = {}
    for r in rows:
        c = closes_of(r[closes_key])
        if c and len(c) == want_len and (r[end_key] or "")[:10] == end_day:
            S[r["n"]] = c
            SEC[r["n"]] = r.get("sec") or "(none)"
    return end_day, S, SEC


def residual_matrix(S: dict[str, list[float]]) -> tuple[list[str], dict[str, list[float]], int]:
    """Names (sorted, deterministic), residual return series per name, aligned length."""
    names = sorted(S)
    R = {n: simple_returns(S[n]) for n in names}
    L = min(len(v) for v in R.values())
    R = {n: v[-L:] for n, v in R.items()}
    mkt = [statistics.mean(R[n][t] for n in names) for t in range(L)]
    return names, {n: residualize(R[n], mkt, L) for n in names}, L


def sector_distributions(names: list[str], mres: dict[str, list[float]],
                         SEC: dict[str, str], min_n: int = 50) -> tuple[list[float], list[float]]:
    """(same_sector_corrs, cross_sector_corrs) over all pairs — the regime yardstick input.
    min_n < 50 is needed for split-half windows (~44 returns); noisier, used for stability
    checks only, never as the headline number."""
    import itertools
    same: list[float] = []
    cross: list[float] = []
    for a, b in itertools.combinations(names, 2):
        rc = pearson(mres[a], mres[b], min_n=min_n)
        if rc is None:
            continue
        (same if SEC[a] == SEC[b] and SEC[a] != "(none)" else cross).append(rc)
    return same, cross
