"""market_refresh.py — de-stale the market layer: core macros + ALL price-series windows.

    SKG_STORAGE_BACKEND=neo4j python pipelines/market_refresh.py

Why this exists (2026-07-02 freshness audit): the 7 core MacroIndicators (환율/금리/유가/금/
달러/KOSPI/S&P) and every :PriceSeries window were written only by loop_build.enrich_market,
which is NOT in the cron path — so they silently froze (^TNX at 06-18) while the 5 state
commodities (market_state_pull) stayed fresh. This script puts the same refresh in the cron,
and verify_artifacts.py now gates on the resulting window-end dates so this class of silent
staleness can never ship again.

Idempotent: write_macro / write_price_series MERGE on stable ids (node count constant).
The price refresh list comes from the EXISTING :PriceSeries nodes — their `ticker` property
is the exact yfinance symbol used at first fetch (incl. .KS/.KQ for KR), so both markets
refresh in place. Dead/delisted tickers simply keep their last window (reported, not hidden).
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import datetime
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import config as cfg
from skg.database import make_repo
from skg.sources.market import MarketFetcher

FRESH_DAYS = 7  # weekend + market-holiday tolerant; matches the artifact gate


def _age_days(window_end: str | None, as_of: str) -> int:
    try:
        return (datetime.date.fromisoformat(as_of[:10])
                - datetime.date.fromisoformat(str(window_end)[:10])).days
    except (ValueError, TypeError):
        return 9999


def main() -> None:
    repo = make_repo(cfg)
    as_of = cfg.AS_OF_NOW
    mf = MarketFetcher(window_days=cfg.PRICE_WINDOW_DAYS)

    # 1) core macro hubs (환율/금리/원자재/지수) — the shared connective-tissue nodes
    print("[refresh] fetching core macro indicators...")
    macros = mf.fetch_macro_indicators(as_of)
    repo.write_macro(macros)
    for m in macros:
        print(f"    {m.name[:20]:20} last={m.last_close}  window_end={m.window_end[:10]}")

    # 2) every stored price-series window (US + KR; symbol comes from the node itself)
    rows = repo.get_price_series_index()
    print(f"[refresh] refreshing {len(rows)} price-series windows (batched)...")
    series = mf.fetch_price_series(rows, as_of)
    repo.write_price_series(series)
    print(f"[refresh] {len(series)}/{len(rows)} series refreshed")

    # 2b) coverage gap: in-universe issuers with a listing but NO series yet (the original
    # enrich_market capped at the first 1500 by CIK order, skipping some index members)
    if hasattr(repo, "_read"):
        missing = repo._read(
            "MATCH (i:Issuer) WHERE ((i.issuer_id STARTS WITH 'CIK' AND "
            "i.index_membership IS NOT NULL) OR i.issuer_id STARTS WITH 'DART') "
            "AND NOT EXISTS {MATCH (i)-[:HAS_PRICE]->()} "
            "MATCH (i)<-[:OF_ISSUER]-(sec:Security)<-[:OF_SECURITY]-(l:Listing) "
            "RETURN i.issuer_id AS iid, sec.security_id AS sid, l.ticker AS ticker, "
            "l.venue AS venue ORDER BY i.issuer_id")
        gap = []
        for r in missing:
            sym = (f"{r['ticker']}.{'KQ' if r['venue'] == 'KQ' else 'KS'}"
                   if r["iid"].startswith("DART") else r["ticker"])
            gap.append((r["iid"], r["sid"], sym))
        if gap:
            print(f"[refresh] coverage gap: {len(gap)} in-universe issuers without a series — fetching...")
            new_series = mf.fetch_price_series(gap, as_of)
            repo.write_price_series(new_series)
            print(f"[refresh] {len(new_series)}/{len(gap)} gap series added")

    # 2c) KR daily snapshot (시가총액/거래대금/당일등락) — ONE key-free FDR call, every cron
    # pass (not gated by SKG_INCLUDE_KR: this is state refresh, not corpus ingestion).
    # Failure is non-fatal: last snapshot's props persist, krx_date exposes their age.
    if hasattr(repo, "set_issuer_krx_state"):
        try:
            from skg.sources.krx import fetch_krx_snapshot
            snap = fetch_krx_snapshot()
            repo.set_issuer_krx_state(snap, as_of)
            print(f"[refresh] KRX snapshot: {len(snap)} rows stamped (mktcap/거래대금/등락)")
        except Exception as e:  # noqa: BLE001 — a scrape hiccup must not kill the cron
            print(f"[refresh] WARN KRX snapshot failed ({type(e).__name__}: {e}) — "
                  "previous snapshot stays, krx_date shows its age")

    # 3) honest staleness report — what is STILL old after the refresh (dead tickers etc.)
    if hasattr(repo, "_read"):
        recs = repo._read("MATCH (p:PriceSeries) RETURN p.ticker AS t, p.window_end AS we")
        stale = sorted((r["t"], str(r["we"])[:10]) for r in recs
                       if _age_days(r["we"], as_of) > FRESH_DAYS)
        pct = round(100 * (len(recs) - len(stale)) / len(recs), 1) if recs else 0.0
        print(f"[refresh] price freshness: {pct}% within {FRESH_DAYS}d of {as_of[:10]} "
              f"({len(stale)} stale)")
        for t, we in stale[:10]:
            print(f"    STALE {t:14} window_end={we}")
        if len(stale) > 10:
            print(f"    ... and {len(stale) - 10} more (likely delisted/dead tickers)")

    print(f"[refresh] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
