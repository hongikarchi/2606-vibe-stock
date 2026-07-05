"""backfill_history.py — ONE-TIME 3y daily-close backfill for the regime reference history.

    SKG_STORAGE_BACKEND=neo4j python pipelines/backfill_history.py

The sufficiency audit's terminal finding on the regime yardstick: reference history n=1 —
"지금이 이례적인가" is unanswerable by definition. This backfills ~3 years of daily closes
for the CURRENT universe (issuers with a PriceSeries) into data/history/px_3y/<market>.json.gz
so regime_yardstick can compute a rolling-window reference distribution (분기별 창들의
same/cross-sector gap 분포) and place the current window as a percentile.

HONEST LIMIT (stated in every consumer): the universe is TODAY's survivors — a 3y backfill
of current constituents has survivorship bias, fine for a co-movement yardstick (we compare
dispersion structure, not returns) but never for performance claims.

Writes one file per market: {"as_of", "tickers": {name: {"sector", "closes", "dates"}}}.
Idempotent (overwrites). Weekly/manual — NOT in the cron.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import gzip
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config as cfg
from skg.database import make_repo

OUT_DIR = cfg.ROOT / "data" / "history" / "px_3y"
BATCH = 60

MARKETS = {
    "KR": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'DART' "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, p.ticker AS ticker, s.name AS sec"),
    "US": ("MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.issuer_id STARTS WITH 'CIK' "
           "AND i.index_membership IS NOT NULL "
           "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
           "RETURN i.name AS n, p.ticker AS ticker, s.name AS sec"),
}


def backfill(repo, market: str, cypher: str) -> None:
    import yfinance as yf
    rows = repo._read(cypher)
    print(f"[backfill] {market}: {len(rows)} tickers, 3y daily (batched {BATCH})...")
    out = {}
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        syms = [r["ticker"] for r in chunk]
        try:
            df = yf.download(syms, period="3y", interval="1d", group_by="ticker",
                             progress=False, auto_adjust=True, threads=True)
        except Exception as e:  # noqa: BLE001
            print(f"    WARN batch {i // BATCH}: {type(e).__name__}")
            continue
        for r in chunk:
            try:
                c = df[r["ticker"]]["Close"].dropna()
                if len(c) < 200:   # need enough history to contribute reference windows
                    continue
                out[r["n"]] = {
                    "sector": r["sec"] or "(none)",
                    "closes": [round(float(x), 4) for x in c.tolist()],
                    "dates": [d.strftime("%Y-%m-%d") for d in c.index],
                }
            except Exception:  # noqa: BLE001
                continue
        print(f"    {min(i + BATCH, len(rows))}/{len(rows)} ({len(out)} kept)")
        time.sleep(0.5)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{market}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"as_of": cfg.AS_OF_NOW, "survivorship": "current-universe backfill",
                   "tickers": out}, f, ensure_ascii=False)
    print(f"[backfill] {market}: {len(out)} tickers -> {path}")


def main() -> None:
    repo = make_repo(cfg)
    for market, cypher in MARKETS.items():
        backfill(repo, market, cypher)
    repo.close()
    print("[backfill] DONE — regime_yardstick can now build the reference distribution")


if __name__ == "__main__":
    main()
