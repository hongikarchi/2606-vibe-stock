"""DartFetcher — Korean issuer master via OpenDART (key required, free).

Mirrors EdgarFetcher so everything downstream (Repository, extract, analyze, viz) is reused.
issuer_id = "DART<corp_code>". corpCode.xml gives all listed issuers + Korean AND English
names (cross-lingual aliases for free). company.json gives industry (induty_code) for the
:Sector clusters — but it's one call per issuer, so we pull it ONLY for the top-N by market
cap (yfinance), since the user only wants blue chips, not 개잡주 shells.

Key from cfg.DART_API_KEY (or env DART_API_KEY). 10k requests/day cap, so we stay bounded.
"""
from __future__ import annotations

import io
import json
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from ..models import Alias, Issuer, Listing, Sector, Security

_BASE = "https://opendart.fss.or.kr/api"
_SENTINEL = "1900-01-01T00:00:00"

# DART induty_code is KSIC (한국표준산업분류). We store the raw code as the sector and let
# the display name come from the issuer's own description; coarse coloring uses the prefix.
_UA = {"User-Agent": "Mozilla/5.0"}


class DartFetcher:
    def __init__(self, api_key: str, min_interval: float = 0.12):
        if not api_key:
            raise ValueError("DART API key required (cfg.DART_API_KEY / env DART_API_KEY)")
        self.key = api_key
        self.min_interval = min_interval
        self._last = 0.0
        self._corp_cache = None

    def _throttle(self):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, path: str, **params) -> bytes:
        self._throttle()
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url = f"{_BASE}/{path}?crtfc_key={self.key}&{qs}"
        return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=30).read()

    # ----------------------------------------------------------------- corp master
    def _listed_corps(self) -> list[dict]:
        """All KRX-listed issuers from corpCode.xml: {corp_code, corp_name, corp_eng_name, stock_code}."""
        if self._corp_cache is None:
            raw = self._get("corpCode.xml")
            z = zipfile.ZipFile(io.BytesIO(raw))
            root = ET.fromstring(z.read(z.namelist()[0]).decode("utf-8"))
            out = []
            for e in root.findall(".//list"):
                stock = (e.findtext("stock_code") or "").strip()
                if not stock:
                    continue  # listed only
                out.append({
                    "corp_code": e.findtext("corp_code"),
                    "corp_name": (e.findtext("corp_name") or "").strip(),
                    "corp_eng_name": (e.findtext("corp_eng_name") or "").strip(),
                    "stock_code": stock,
                })
            self._corp_cache = out
        return self._corp_cache

    def rank_by_market_cap(self, top_n: int) -> list[dict]:
        """Top-N listed corps by market cap. DART has no market-cap, so we join the corpCode
        master to KRX's bulk market-cap table (FinanceDataReader, ONE call for the whole
        market) on the 6-digit stock_code. This keeps blue chips and drops 개잡주 shells
        with zero per-ticker calls. The Market column gives venue (.KS vs .KQ) directly."""
        import FinanceDataReader as fdr
        krx = fdr.StockListing("KRX")
        capcol = next((c for c in krx.columns if c.lower() in ("marcap", "marketcap")), None)
        # code -> (marcap, venue) from the bulk table
        cap = {}
        for _, r in krx.iterrows():
            code = str(r.get("Code", "")).zfill(6)
            mc = r.get(capcol)
            mkt = r.get("Market", "")
            venue = "KQ" if "KOSDAQ" in str(mkt).upper() else "KS"
            if mc and mc == mc:  # not NaN
                cap[code] = (float(mc), venue)
        corps = {c["stock_code"]: c for c in self._listed_corps()}
        joined = []
        for code, c in corps.items():
            if code in cap:
                mc, venue = cap[code]
                cc = dict(c); cc["market_cap"] = mc; cc["venue"] = venue
                joined.append(cc)
        joined.sort(key=lambda x: x["market_cap"], reverse=True)
        return joined[:top_n]

    # ----------------------------------------------------------------- issuer master
    def issuer_master(self, corps: list[dict]) -> tuple[list, list, list, list]:
        """Map selected corps -> (issuers, securities, listings, aliases). Cross-lingual:
        BOTH the Korean and English name become aliases pointing at the same issuer_id."""
        issuers, securities, listings, aliases = [], [], [], []
        for c in corps:
            iid = f"DART{c['corp_code']}"
            name = c["corp_name"]
            venue = c.get("venue", "KS")
            issuers.append(Issuer(iid, name, "listed", _SENTINEL, None, _SENTINEL))
            sec_id = f"{c['stock_code']}.KR"
            securities.append(Security(sec_id, iid, "common"))
            listings.append(Listing(f"KR_{c['stock_code']}", sec_id, c["stock_code"], venue))
            # cross-lingual aliases (KO + EN) -> SAME node. No fuzzy matching needed.
            aliases.append(Alias(name, "ko", "issuer", iid, _SENTINEL, None))
            if c.get("corp_eng_name"):
                aliases.append(Alias(c["corp_eng_name"], "en", "issuer", iid, _SENTINEL, None))
            aliases.append(Alias(c["stock_code"], "ko", "issuer", iid, _SENTINEL, None))
        return issuers, securities, listings, aliases

    def fetch_sectors(self, corps: list[dict], knowledge_time: str = _SENTINEL) -> list[Sector]:
        """company.json induty_code -> :Sector edge, ONE call per issuer (bounded to top-N)."""
        sectors = []
        for c in corps:
            try:
                cj = json.loads(self._get("company.json", corp_code=c["corp_code"]))
            except Exception:  # noqa: BLE001
                continue
            if cj.get("status") != "000":
                continue
            code = (cj.get("induty_code") or "").strip()
            if not code:
                continue
            sectors.append(Sector(
                sector_id=f"KSIC:{code}", sic_code=code,
                name=f"KSIC {code}", issuer_id=f"DART{c['corp_code']}",
                event_time=knowledge_time, knowledge_time=knowledge_time,
            ))
        return sectors
