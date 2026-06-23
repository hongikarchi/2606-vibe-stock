"""comovement_trial.py — SMALL-SCALE trial of observed price<->macro co-movement edges.

    SKG_STORAGE_BACKEND=neo4j python comovement_trial.py

Connects the disjoint US/KR blocks through the shared macro hubs, using DESCRIPTIVE past
correlation (NOT a signal — every edge is windowed, is_exploratory, and disclaimered).
Trial scope: a handful of top US + top KR issuers vs the 7 macro indicators, so we can see
how the picture changes before any full-scale application.
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.models import MacroIndicator, PriceSeries
from skg.sources.market import MarketFetcher
from skg.store import make_repo

N_US = int(__import__("os").environ.get("SKG_CM_US", "20"))
N_KR = int(__import__("os").environ.get("SKG_CM_KR", "20"))


def _price_rows(repo, where: str, n: int):
    rows = repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE " + where +
        " RETURN p {.*} AS p LIMIT $n", n=n)
    out = []
    for r in rows:
        p = r["p"]
        out.append(PriceSeries(
            series_id=p["series_id"], security_id=p["security_id"], issuer_id=p["issuer_id"],
            ticker=p["ticker"], last_close=p["last_close"], window_start=p["window_start"],
            window_end=p["window_end"], pct_change_window=p["pct_change_window"],
            vol_window=p["vol_window"], recent_closes_json=p["recent_closes_json"],
            returns_json=p["returns_json"], event_time=p.get("event_time", ""),
            knowledge_time=p.get("knowledge_time", "")))
    return out


def main() -> None:
    repo = make_repo(cfg)
    # macro nodes -> MacroIndicator objects (for return recomputation)
    macros = []
    for r in repo._read("MATCH (m:MacroIndicator) RETURN m {.*} AS m"):
        m = r["m"]
        macros.append(MacroIndicator(
            indicator_id=m["indicator_id"], ticker=m["ticker"], name=m["name"],
            category=m["category"], last_close=m["last_close"], window_start=m["window_start"],
            window_end=m["window_end"], pct_change_window=m["pct_change_window"],
            recent_closes_json=m["recent_closes_json"]))

    us = _price_rows(repo, "i.issuer_id STARTS WITH 'CIK'", N_US)
    kr = _price_rows(repo, "i.issuer_id STARTS WITH 'DART'", N_KR)
    prices = us + kr
    print(f"[comovement] trial scope: {len(us)} US + {len(kr)} KR price series vs {len(macros)} macro")

    edges = MarketFetcher.compute_comovements(prices, macros, cfg.AS_OF_NOW,
                                              corr_floor=0.5, min_obs=60)
    repo.write_comovements(edges)
    print(f"[comovement] wrote {len(edges)} CO_MOVES_WITH edges (|corr|>=0.5, n>=60, exploratory)")

    # show what connected to what (honest: these are PAST correlations, not predictions)
    rows = repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries)-[c:CO_MOVES_WITH]->(m:MacroIndicator) "
        "RETURN i.name AS issuer, m.name AS macro, c.corr AS corr, c.n_obs AS n "
        "ORDER BY abs(c.corr) DESC LIMIT 12")
    print("[comovement] strongest observed co-movements (past window — NOT a signal):")
    for r in rows:
        sign = "동조" if r["corr"] > 0 else "역(逆)"
        print(f"    {r['issuer'][:22]:22} {sign} {r['macro'][:14]:14} r={r['corr']:+.2f} (n={r['n']})")

    # did it connect the markets? count issuers per macro hub
    print("[comovement] macro hubs now connecting issuers (cross-market tissue):")
    for r in repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(:PriceSeries)-[:CO_MOVES_WITH]->(m:MacroIndicator) "
        "RETURN m.name AS macro, count(DISTINCT i) AS issuers ORDER BY issuers DESC"):
        print(f"    {r['macro'][:18]:18} <- {r['issuers']} issuers")
    repo.close()


if __name__ == "__main__":
    main()
