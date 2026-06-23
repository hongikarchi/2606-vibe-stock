"""EdgarFetcher — key-free SEC EDGAR ingest.

EDGAR needs no API key, only a contactable User-Agent header (cfg.EDGAR_USER_AGENT);
without it data.sec.gov returns 403. Rate limit is 10 req/s per IP — we stay polite below.

Two outputs, both shapes the offline pipeline already consumes:
  - fetch_issuer_universe(): company_tickers.json -> issuer_master tuples (issuer_id="CIK##########")
  - fetch_filings_as_documents(cik): submissions/CIK*.json filings.recent -> corpus Document dicts

We do NOT download filing bodies (megabytes of HTML). Each Document's `text` is COMPOSED
from the structured 8-K fields, which (a) keeps docs tiny, (b) gives the rule extractor
real prose with EXACT offsets so source_span/span_start/span_end are correct, and
(c) is fully deterministic.
"""
from __future__ import annotations

import json
import time
import urllib.request

from ..models import Alias, Issuer, Listing, Sector, Security

_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Sentinel: EDGAR issuers are treated as always-active for any as_of (we don't have a
# reliable per-issuer listing-start feed without extra calls). status_valid_to=None.
_SENTINEL = "1900-01-01T00:00:00"

# Common 8-K item codes -> human description. The composed text cites these verbatim, and
# the rule extractor (skg/extract/edgar_rules.py) keys risk_flag stance off the code.
ITEM_DESCRIPTIONS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate a Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Listing Rule",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


def _norm_ts(s: str) -> str:
    """EDGAR formerNames timestamps look like '2007-01-10T05:00:00.000Z'. Normalize to the
    plain ISO-8601 the rest of the system uses (lexically comparable, no fractional/Z)."""
    if not s:
        return s
    s = s.replace("Z", "").split(".")[0]
    return s


class EdgarFetcher:
    def __init__(self, user_agent: str, min_interval: float = 0.13):
        # 0.13s between calls -> ~7.7 req/s, comfortably under SEC's 10 req/s.
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self.min_interval = min_interval
        self._last = 0.0
        self._tickers_cache = None

    # ----------------------------------------------------------------- http
    def _get(self, url: str):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            data = json.loads(raw)
        self._last = time.monotonic()
        return data

    def _tickers(self):
        if self._tickers_cache is None:
            ct = self._get(_COMPANY_TICKERS)
            # dict keyed "0".."N", already ordered -> deterministic list
            self._tickers_cache = [ct[k] for k in sorted(ct, key=int)]
        return self._tickers_cache

    # ----------------------------------------------------------------- universe
    def cik_batch(self, offset: int, limit: int) -> list[int]:
        """Deterministic slice of CIKs from the ordered company_tickers list."""
        rows = self._tickers()[offset:offset + limit]
        return [r["cik_str"] for r in rows]

    def universe_size(self) -> int:
        return len(self._tickers())

    def fetch_issuer_universe(self, offset: int = 0, limit: int | None = None):
        """Return (issuers, securities, listings, aliases) for a slice of the ticker list.
        Each maps one company_tickers row WITHOUT a submissions call (cheap, breadth-first).
        issuer_id = 'CIK##########'. ticker + title become time-scoped aliases."""
        rows = self._tickers()
        if limit is not None:
            rows = rows[offset:offset + limit]
        issuers, securities, listings, aliases = [], [], [], []
        for r in rows:
            cik = r["cik_str"]
            iid = f"CIK{cik:010d}"
            ticker = r["ticker"]
            title = r["title"]
            issuers.append(Issuer(iid, title, "listed", _SENTINEL, None, _SENTINEL))
            sec_id = f"{ticker}.US"
            securities.append(Security(sec_id, iid, "common"))
            listings.append(Listing(f"US_{ticker}", sec_id, ticker, "US"))
            # surface forms -> this issuer (always-valid). Dedup-safe via MERGE downstream.
            aliases.append(Alias(ticker, "en", "issuer", iid, _SENTINEL, None))
            aliases.append(Alias(title, "en", "issuer", iid, _SENTINEL, None))
        return issuers, securities, listings, aliases

    @staticmethod
    def _aliases_from_submission(sub: dict, cik: int) -> list[Alias]:
        """formerNames -> real time-scoped aliases (e.g. Apple Computer -> Apple Inc.)."""
        iid = f"CIK{cik:010d}"
        return [
            Alias(fn["name"], "en", "issuer", iid,
                  _norm_ts(fn.get("from", "")) or _SENTINEL, _norm_ts(fn.get("to")))
            for fn in sub.get("formerNames", [])
        ]

    @staticmethod
    def _sector_from_submission(sub: dict, cik: int, knowledge_time: str) -> Sector | None:
        """Top-level sic/sicDescription -> a Sector row (issuer->sector edge). Free: the
        submissions JSON is already fetched, so capturing SIC costs zero extra HTTP."""
        sic = (sub.get("sic") or "").strip()
        if not sic:
            return None
        return Sector(
            sector_id=f"SIC:{sic}", sic_code=sic,
            name=sub.get("sicDescription", "") or f"SIC {sic}",
            issuer_id=f"CIK{cik:010d}",
            event_time=knowledge_time, knowledge_time=knowledge_time,
        )

    def fetch_issuer_filings_and_aliases(
        self, cik: int, forms=("8-K",), max_docs: int = 20
    ) -> tuple[list[dict], list[Alias], "Sector | None"]:
        """ONE submissions GET -> (filing Documents, formerNames aliases, SIC sector).
        Fetching all three from a single response keeps EDGAR calls minimal (matters at
        universe scale against the 10 req/s limit)."""
        sub = self._get(_SUBMISSIONS.format(cik=cik))
        kt = _SENTINEL  # issuer master is always-active; sector knowledge stamped at sentinel
        return (self._docs_from_submission(sub, cik, forms, max_docs),
                self._aliases_from_submission(sub, cik),
                self._sector_from_submission(sub, cik, kt))

    def fetch_filings_as_documents(
        self, cik: int, forms=("8-K",), max_docs: int = 20
    ) -> list[dict]:
        """submissions filings.recent -> compact corpus Document dicts (deterministic)."""
        return self._docs_from_submission(
            self._get(_SUBMISSIONS.format(cik=cik)), cik, forms, max_docs
        )

    # ----------------------------------------------------------------- filings
    def _docs_from_submission(self, sub: dict, cik: int, forms, max_docs: int) -> list[dict]:
        """submissions filings.recent -> compact corpus Document dicts. doc_id is stable per
        accession so re-fetch never duplicates."""
        name = sub.get("name", f"CIK{cik:010d}")
        iid = f"CIK{cik:010d}"
        rec = sub.get("filings", {}).get("recent", {})
        forms_arr = rec.get("form", [])
        docs = []
        for i, form in enumerate(forms_arr):
            if form not in forms:
                continue
            acc = rec["accessionNumber"][i]
            filing_date = rec["filingDate"][i]
            items = rec.get("items", [""] * len(forms_arr))[i]
            text = self._compose_8k_text(name, iid, form, filing_date, items, acc)
            event_time = f"{filing_date}T00:00:00"
            docs.append({
                "doc_id": f"edgar_{cik:010d}_{acc.replace('-', '')}",
                "source_id": "edgar",
                "lang": "en",
                "text": text,
                "event_time": event_time,
                "ingest_time": event_time,
                # carried for the rule extractor (not part of the Document dataclass):
                "_cik": cik, "_items": items, "_issuer_name": name, "_issuer_id": iid,
            })
            if len(docs) >= max_docs:
                break
        return docs

    @staticmethod
    def _compose_8k_text(name, iid, form, filing_date, items, acc) -> str:
        """Build short, deterministic prose from structured fields. The rule extractor
        relies on the exact ', ' join so its span offsets land on item descriptions."""
        codes = [c.strip() for c in items.split(",") if c.strip()] if items else []
        if codes:
            described = "; ".join(
                f"{c} {ITEM_DESCRIPTIONS.get(c, 'Other Item')}" for c in codes
            )
            item_clause = f" Reported items: {described}."
        else:
            item_clause = ""
        return (
            f"{name} ({iid}) filed a {form} on {filing_date}.{item_clause} "
            f"Accession {acc}."
        )
