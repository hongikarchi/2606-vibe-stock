"""universe.py — the SINGLE in-universe predicate for issuers (junk-cut).

The graph crawled the entire SEC ticker list (~4,275 US issuers), most of them micro-cap
shells that pollute associations and the theme "관련 기업" lift ranking. The user wants the
ISSUER universe restricted to clear index membership (US: S&P500 + NASDAQ-100) — while NEWS
and MACRO ingestion stay broad. KR is already market-cap top-300, so it's all in-universe.

Index constituents are fetched at build time (FinanceDataReader for S&P500; Wikipedia via
pandas for NASDAQ-100 — both key-free) and mapped ticker -> CIK using the same SEC
company_tickers.json the EDGAR fetcher already uses. Membership is then stamped on Issuer
nodes (index_membership) so all five selection sites can route through is_in_universe().
"""
from __future__ import annotations

import json
import re
import urllib.request


def _norm(sym: str) -> str:
    """Normalize a ticker for joining: strip dots/dashes, uppercase (BRK.B == BRK-B == BRKB)."""
    return re.sub(r"[.\-]", "", str(sym or "")).upper()


def sp500_symbols() -> set[str]:
    import FinanceDataReader as fdr
    df = fdr.StockListing("S&P500")
    return {_norm(s) for s in df["Symbol"].tolist()}


def nasdaq100_symbols() -> set[str]:
    """NASDAQ-100 constituents from Wikipedia (the constituents table has a 'Ticker' column)."""
    import pandas as pd
    tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100",
                          storage_options={"User-Agent": "Mozilla/5.0 skg"})
    for t in tables:
        cols = [str(c) for c in t.columns]
        tcol = next((c for c in t.columns if str(c) in ("Ticker", "Symbol")), None)
        if tcol is not None and 80 <= len(t) <= 120:  # the ~101-row constituents table
            return {_norm(s) for s in t[tcol].astype(str).tolist() if s and s != "nan"}
    return set()


def sec_ticker_to_cik() -> dict[str, str]:
    """SEC company_tickers.json -> {normalized_ticker: 'CIK##########'} (same source as edgar.py)."""
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json",
                                 headers={"User-Agent": "skg universe builder skg@example.com"})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return {_norm(row["ticker"]): f"CIK{int(row['cik_str']):010d}" for row in data.values()}


def us_universe_ciks() -> dict[str, list[str]]:
    """{cik: [memberships]} for S&P500 ∪ NASDAQ-100, mapped to CIK ids."""
    t2c = sec_ticker_to_cik()
    sp = sp500_symbols()
    nq = nasdaq100_symbols()
    out: dict[str, list[str]] = {}
    for sym in sp:
        cik = t2c.get(sym)
        if cik:
            out.setdefault(cik, []).append("S&P500")
    for sym in nq:
        cik = t2c.get(sym)
        if cik:
            out.setdefault(cik, []).append("NASDAQ100")
    return out


def is_in_universe(issuer_id: str, membership: str | None) -> bool:
    """Single predicate routed through all selection sites.
    KR (DART...) is already market-cap top-300 -> always in-universe.
    US (CIK...) is in-universe iff it carries an index membership tag."""
    if issuer_id.startswith("DART"):
        return True
    return bool(membership)
