"""market_state.py — descriptive 'where is the market right now' indicators.

Two key-free, principle-safe market-state reads (OBSERVATION, not prediction/signal):

  1) 52-week position per issuer = (price - 52w_low) / (52w_high - 52w_low). Aggregated, this
     is MARKET BREADTH: what fraction of names sit near their highs vs lows — an objective
     overheated/depressed read the human interprets.
  2) Commodity / memory-proxy prices (gold, oil, copper, silver, gas; Micron + SOXX for memory).

No lead/lag — the stability test showed daily lead-lag flips across regimes and is too weak to
assert. This module only states the CURRENT cross-sectional state.
"""
from __future__ import annotations

import time

# Commodity + memory-proxy series to add as MacroIndicator-style state (key-free yfinance).
STATE_TICKERS = {
    "HG=F":  ("구리 / Copper", "commodity"),
    "SI=F":  ("은 / Silver", "commodity"),
    "NG=F":  ("천연가스 / NatGas", "commodity"),
    "MU":    ("마이크론 (메모리 프록시)", "memory_proxy"),
    "SOXX":  ("반도체 ETF (SOXX)", "memory_proxy"),
}


def fetch_52w_position(issuer_tickers, knowledge_time, batch=80):
    """issuer_tickers = [(issuer_id, yf_symbol)]. Returns {issuer_id: position_pct (0-100)}.
    52w position from a 1-year daily batch download (no slow per-ticker .info)."""
    import yfinance as yf
    pos = {}
    for i in range(0, len(issuer_tickers), batch):
        chunk = issuer_tickers[i:i + batch]
        syms = [s for _, s in chunk]
        try:
            df = yf.download(syms, period="1y", interval="1d", group_by="ticker",
                             progress=False, auto_adjust=True, threads=True)
        except Exception:  # noqa: BLE001
            continue
        for iid, sym in chunk:
            try:
                c = df[sym]["Close"].dropna()
                if len(c) < 50:
                    continue
                hi, lo, cur = float(c.max()), float(c.min()), float(c.iloc[-1])
                if hi > lo:
                    pos[iid] = round((cur - lo) / (hi - lo) * 100, 1)
            except Exception:  # noqa: BLE001
                continue
        time.sleep(0.3)  # polite between batches
    return pos


def breadth_summary(positions: dict) -> dict:
    """Cross-sectional market breadth from per-issuer 52w positions."""
    vals = list(positions.values())
    if not vals:
        return {}
    n = len(vals)
    near_high = sum(1 for v in vals if v >= 80)   # within 20% of 52w high
    near_low = sum(1 for v in vals if v <= 20)
    return {
        "n": n,
        "pct_near_high": round(100 * near_high / n, 1),
        "pct_near_low": round(100 * near_low / n, 1),
        "median_position": round(sorted(vals)[n // 2], 1),
    }


def fetch_state_indicators(knowledge_time):
    """Commodity + memory-proxy current levels as MacroIndicator rows (reuse the macro layer)."""
    import json
    import yfinance as yf
    from ..models import MacroIndicator
    out = []
    df = None
    try:
        df = yf.download(list(STATE_TICKERS), period="3mo", interval="1d", group_by="ticker",
                         progress=False, auto_adjust=True, threads=True)
    except Exception:  # noqa: BLE001
        return out
    for ticker, (name, cat) in STATE_TICKERS.items():
        try:
            c = df[ticker]["Close"].dropna()
            closes = [round(float(x), 4) for x in c.tolist()][-90:]
            dates = [d.strftime("%Y-%m-%dT00:00:00") for d in c.index][-90:]
            if not closes:
                continue
            pct = round((closes[-1] / closes[0] - 1.0), 4) if closes[0] else 0.0
            out.append(MacroIndicator(
                indicator_id=f"MACRO:{ticker}", ticker=ticker, name=name, category=cat,
                last_close=closes[-1], window_start=dates[0], window_end=dates[-1],
                pct_change_window=pct, recent_closes_json=json.dumps(closes),
                event_time=dates[-1], knowledge_time=knowledge_time))
        except Exception:  # noqa: BLE001
            continue
    return out
