"""fundamentals_pull.py — US shares-outstanding / market-cap seed (weekly/manual, NOT cron).

    SKG_STORAGE_BACKEND=neo4j python pipelines/fundamentals_pull.py

Stamps i.shares_outstanding + i.mktcap_raw on US issuers that have a PriceSeries, via
yfinance fast_info (one call per ticker — bounded, slow-moving data, so this runs weekly or
on demand, never in the 3x/day cron). The treemap's DAILY US market cap is then derived at
export time as shares_outstanding × last_close (fresh every cron, zero API cost);
mktcap_raw is the fallback when shares are missing. KR needs none of this — the KRX
snapshot (market_refresh) delivers Marcap directly every pass.
"""
from __future__ import annotations

import os
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import time

import config as cfg
from skg.database import make_repo

MAX_ISSUERS = int(os.environ.get("SKG_FUNDAMENTALS_MAX", "1700"))


def main() -> None:
    repo = make_repo(cfg)
    rows = repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) "
        "WHERE i.issuer_id STARTS WITH 'CIK' "
        "RETURN i.issuer_id AS iid, p.ticker AS ticker ORDER BY i.issuer_id LIMIT $n",
        n=MAX_ISSUERS)
    print(f"[fundamentals] fetching shares outstanding / mktcap for {len(rows)} US issuers "
          "(fast_info, per-ticker — weekly cadence)...")
    import yfinance as yf
    out, fail = [], 0
    for k, r in enumerate(rows):
        try:
            fi = yf.Ticker(r["ticker"]).fast_info
            sh = float(fi.get("shares") or 0) or None
            cap = float(fi.get("market_cap") or 0) or None
            if sh or cap:
                out.append({"iid": r["iid"], "sh": sh, "cap": cap})
        except Exception:  # noqa: BLE001 — one bad ticker must not kill the seed
            fail += 1
        if k % 200 == 199:
            print(f"    {k + 1}/{len(rows)} done ({len(out)} ok, {fail} failed)")
            time.sleep(1.0)
    repo._write(
        "UNWIND $rows AS r MATCH (i:Issuer {issuer_id: r.iid}) "
        "SET i.shares_outstanding = r.sh, i.mktcap_raw = r.cap, "
        "    i.fundamentals_kt = $kt",
        rows=out, kt=cfg.AS_OF_NOW)
    print(f"[fundamentals] {len(out)}/{len(rows)} issuers stamped "
          f"(shares+cap; {fail} tickers failed). nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
