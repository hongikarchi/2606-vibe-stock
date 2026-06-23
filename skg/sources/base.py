"""SourceFetcher — the real-ingest seam contract.

A fetcher turns an external registry (SEC EDGAR, OpenDART, ...) into the two shapes the
offline pipeline already consumes, so swapping data sources changes nothing downstream:

  - fetch_issuer_universe(limit) -> (issuers, securities, listings, aliases)
        same tuple `run.py::_load_issuer_master` returns, anchored to an authoritative id.
  - fetch_filings_as_documents(...) -> list[dict]
        corpus Document dicts in the `ingest.read_corpus` shape
        (doc_id, source_id, lang, text, event_time, ingest_time).
"""
from __future__ import annotations

from typing import Protocol

from ..models import Alias, Issuer, Listing, Security


class SourceFetcher(Protocol):
    def fetch_issuer_universe(
        self, limit: int | None = None
    ) -> tuple[list[Issuer], list[Security], list[Listing], list[Alias]]: ...

    def fetch_filings_as_documents(self, issuer_id: str, **kw) -> list[dict]: ...
