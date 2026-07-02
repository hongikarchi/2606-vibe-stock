"""krx — one-call KR market snapshot via FinanceDataReader StockListing('KRX').

The same single call dart.rank_by_market_cap already makes at pull time returns, per listed
company: Close, ChagesRatio (FDR's typo'd daily-% column), Volume, Amount (거래대금, KRW),
Marcap (시가총액, KRW). We previously used Marcap transiently for sorting and THREW IT AWAY —
this module returns the full snapshot so market_refresh can stamp 시가총액/거래대금/당일등락
onto :Issuer nodes every cron pass (KR needs no per-ticker fetches at all).

Kept separate from DartFetcher (which requires an API key in its constructor); this is
key-free. Column names are selected defensively (FDR renames across versions — dart.py:80
precedent).
"""
from __future__ import annotations


def _col(df, *names):
    """First matching column name (FDR renames across versions, e.g. ChagesRatio typo)."""
    for n in names:
        if n in df.columns:
            return n
    return None


def fetch_krx_snapshot() -> list[dict]:
    """[{code, close, chg_pct, volume, amount, marcap, venue}] for every KRX-listed company.
    chg_pct is a FRACTION (FDR gives percent). One scrape-based call — callers must treat
    failure as non-fatal (the previous snapshot's node props simply stay, dated by krx_date)."""
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX")
    c_code = _col(df, "Code", "Symbol")
    c_close = _col(df, "Close")
    c_chg = _col(df, "ChagesRatio", "ChangesRatio", "ChangeRatio")
    c_vol = _col(df, "Volume")
    c_amt = _col(df, "Amount")
    c_cap = _col(df, "Marcap", "MarketCap")
    c_mkt = _col(df, "Market")
    if not (c_code and c_cap):
        raise RuntimeError(f"FDR StockListing('KRX') columns changed: {list(df.columns)}")
    out = []
    for _, row in df.iterrows():
        code = str(row[c_code]).zfill(6)
        try:
            out.append({
                "code": code,
                "close": float(row[c_close]) if c_close else 0.0,
                "chg_pct": round(float(row[c_chg]) / 100.0, 4) if c_chg else None,
                "volume": float(row[c_vol]) if c_vol else 0.0,
                "amount": float(row[c_amt]) if c_amt else 0.0,
                "marcap": float(row[c_cap]) if c_cap else 0.0,
                "venue": "KQ" if str(row.get(c_mkt, "")).upper().startswith("KOSDAQ") else "KS",
            })
        except (TypeError, ValueError):
            continue
    return out
