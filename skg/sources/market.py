"""MarketFetcher — key-free market/macro data via yfinance.

ONE library covers everything the user named: equity prices, FX (KRW=X), rates (^TNX),
commodities (GC=F, CL=F), dollar index (DX-Y.NYB), indices (^KS11, ^GSPC). No API key.

Modeling: one :PriceSeries node per ticker (NOT one per day) carrying a bounded rolling
window of recent closes + precomputed log-returns as JSON. One :MacroIndicator per macro
ticker. This keeps the node count constant across loop runs (window is overwritten via
SET n += r) and avoids exploding the graph with millions of day-nodes.

Determinism: windows are fixed-length and sorted before JSON-encoding, so two runs over the
same bars produce byte-identical series_json. Bi-temporal: event_time = last bar's date,
knowledge_time = fetch time (passed in, since Date.now() is avoided in the pipeline).
"""
from __future__ import annotations

import json
import math
import time

from ..models import MacroIndicator, PriceSeries

# Macro/market reference series — small fixed set (these become shared hub nodes).
MACRO_TICKERS = {
    "KRW=X":     ("USD/KRW 환율", "fx"),
    "^TNX":      ("미 10년물 국채금리", "rate"),
    "GC=F":      ("금 / Gold", "commodity"),
    "CL=F":      ("WTI 원유", "commodity"),
    "DX-Y.NYB":  ("달러 인덱스", "dollar_index"),
    "^KS11":     ("KOSPI", "index"),
    "^GSPC":     ("S&P 500", "index"),
}


def _log_returns(closes: list[float]) -> list[float]:
    out = []
    for a, b in zip(closes, closes[1:]):
        if a > 0 and b > 0:
            out.append(round(math.log(b / a), 6))
    return out


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _pearson(a: list[float], b: list[float]) -> float:
    """Pearson correlation of two equal-length series. 0.0 if undefined (flat series)."""
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va > 0 and vb > 0 else 0.0


class MarketFetcher:
    def __init__(self, window_days: int = 90, period: str = "6mo", min_interval: float = 1.0):
        self.window = window_days
        self.period = period
        self.min_interval = min_interval
        self._last = 0.0

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _download(self, tickers: list[str]):
        import yfinance as yf
        self._throttle()
        return yf.download(tickers, period=self.period, interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True,
                           threads=False)

    @staticmethod
    def _closes_for(df, ticker: str) -> tuple[list[float], list[str]]:
        """Return (closes, iso_dates) for one ticker from a group_by='ticker' frame."""
        try:
            s = df[ticker]["Close"].dropna()
        except (KeyError, TypeError):
            return [], []
        closes = [round(float(x), 4) for x in s.tolist()]
        dates = [d.strftime("%Y-%m-%dT00:00:00") for d in s.index]
        return closes, dates

    # ----------------------------------------------------------------- macro
    def fetch_macro_indicators(self, knowledge_time: str) -> list[MacroIndicator]:
        df = self._download(list(MACRO_TICKERS))
        out = []
        for ticker, (name, category) in MACRO_TICKERS.items():
            closes, dates = self._closes_for(df, ticker)
            closes, dates = closes[-self.window:], dates[-self.window:]
            if not closes:
                continue
            pct = round((closes[-1] / closes[0] - 1.0), 4) if closes[0] else 0.0
            out.append(MacroIndicator(
                indicator_id=f"MACRO:{ticker}", ticker=ticker, name=name, category=category,
                last_close=closes[-1], window_start=dates[0], window_end=dates[-1],
                pct_change_window=pct,
                recent_closes_json=json.dumps(closes),
                event_time=dates[-1], knowledge_time=knowledge_time,
            ))
        return out

    # ------------------------------------------------------- co-movement (gated/labeled)
    @staticmethod
    def compute_comovements(price_rows, macro_rows, knowledge_time: str,
                            corr_floor: float = 0.5, min_obs: int = 60) -> list[dict]:
        """Observed historical co-movement between each price series and each macro series,
        from ALIGNED daily log-returns (Pearson). This is DESCRIPTIVE PAST DATA, never a
        prediction — every edge is windowed, labeled is_exploratory, and carries a disclaimer.
        Only |corr|>=floor with >=min_obs aligned observations survive (cuts spurious noise).

        Returns plain edge dicts; the repo MERGEs them. corr/window/disclaimer live on the EDGE.
        """
        # macro returns by ticker (recompute from closes since macro has no returns_json)
        macro_ret = {}
        for m in macro_rows:
            closes = json.loads(m.recent_closes_json)
            macro_ret[m.indicator_id] = (_log_returns(closes), m.window_start, m.window_end)
        edges = []
        for p in price_rows:
            prets = json.loads(p.returns_json)
            for mid, (mrets, mws, mwe) in macro_ret.items():
                n = min(len(prets), len(mrets))
                if n < min_obs:
                    continue
                a, b = prets[-n:], mrets[-n:]  # align by tail (most recent n returns)
                r = _pearson(a, b)
                if abs(r) < corr_floor:
                    continue
                edges.append({
                    "series_id": p.series_id, "indicator_id": mid,
                    "corr": round(r, 3), "n_obs": n,
                    "window_start": max(p.window_start, mws), "window_end": min(p.window_end, mwe),
                    "method": "pearson_logret_daily", "is_exploratory": True,
                    "disclaimer": "관측된 과거 상관 · 상관≠인과 · 신호 아님 / observed historical "
                                  "correlation over the stated window, NOT causation, NOT a signal",
                    "event_time": knowledge_time, "knowledge_time": knowledge_time,
                })
        return edges

    # ----------------------------------------------------------------- prices
    def fetch_price_series(self, issuer_tickers: list[tuple[str, str, str]],
                           knowledge_time: str, batch: int = 50) -> list[PriceSeries]:
        """issuer_tickers = [(issuer_id, security_id, ticker)]. Batched downloads keep
        yfinance calls few. Returns one PriceSeries per ticker that has data."""
        out = []
        for i in range(0, len(issuer_tickers), batch):
            chunk = issuer_tickers[i:i + batch]
            syms = [t for _, _, t in chunk]
            try:
                df = self._download(syms)
            except Exception:  # noqa: BLE001 — a bad batch must not kill the loop
                continue
            for issuer_id, security_id, ticker in chunk:
                closes, dates = self._closes_for(df, ticker)
                closes, dates = closes[-self.window:], dates[-self.window:]
                if len(closes) < 2:
                    continue
                rets = _log_returns(closes)
                pct = round((closes[-1] / closes[0] - 1.0), 4) if closes[0] else 0.0
                vol = round(_stdev(rets) * math.sqrt(252), 4)  # annualized (descriptive)
                out.append(PriceSeries(
                    series_id=f"PX:{security_id}", security_id=security_id,
                    issuer_id=issuer_id, ticker=ticker, last_close=closes[-1],
                    window_start=dates[0], window_end=dates[-1], pct_change_window=pct,
                    vol_window=vol, recent_closes_json=json.dumps(closes),
                    returns_json=json.dumps(rets),
                    event_time=dates[-1], knowledge_time=knowledge_time,
                ))
        return out

    # --------------------------------------------- analyst ratings (관측, NOT a signal)
    def fetch_ratings(self, issuer_tickers, knowledge_time: str, max_changes: int = 6):
        """Per-issuer analyst data: consensus (mean target, # analysts, rating) + recent
        per-firm rating CHANGES (firm, to-grade, action, target, date). This is OBSERVATION
        of what institutions DID/SAID — never our own recommendation. US has firm-level
        changes; KR (.KS/.KQ) yfinance gives consensus only. One Ticker call per issuer
        (slower) so this runs on a bounded top-N, not the whole universe.
        """
        import yfinance as yf
        out = []
        for issuer_id, security_id, ticker in issuer_tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.info
                consensus = {
                    "target_mean": info.get("targetMeanPrice"),
                    "target_high": info.get("targetHighPrice"),
                    "target_low": info.get("targetLowPrice"),
                    "n_analysts": info.get("numberOfAnalystOpinions"),
                    "rating": info.get("recommendationKey"),
                }
                if not consensus["n_analysts"]:
                    continue  # no analyst coverage -> skip
                changes = []
                try:
                    ud = t.upgrades_downgrades
                    if ud is not None and len(ud):
                        for d, row in ud.sort_index(ascending=False).head(max_changes).iterrows():
                            changes.append({
                                "date": str(d)[:10], "firm": str(row.get("Firm", "")),
                                "to": str(row.get("ToGrade", "")), "from": str(row.get("FromGrade", "")),
                                "action": str(row.get("Action", "")),
                                "target": float(row.get("currentPriceTarget") or 0) or None,
                            })
                except Exception:  # noqa: BLE001
                    pass
                out.append({
                    "issuer_id": issuer_id, "consensus": consensus, "changes": changes,
                    "knowledge_time": knowledge_time,
                    "disclaimer": "기관 동향 관측 · 우리 추천 아님 / observed institutional "
                                  "ratings, NOT our recommendation",
                })
            except Exception:  # noqa: BLE001 — a bad ticker must not kill the batch
                continue
        return out
