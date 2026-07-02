"""Repository — the storage swap seam.

Every READ takes `as_of` so the bi-temporal point-in-time contract lives in the
INTERFACE, not the engine. The later Postgres(AGE)/Graphiti fork (research 01b "open
storage spine") becomes a new Repository implementation; nothing else in the pipeline
changes. networkx is COMPUTE that consumes these reads — it is NOT behind this seam.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import (
    AnalysisResult,
    Claim,
    Issuer,
    Mention,
    Source,
)


class Repository(ABC):
    # ---- writes ----
    @abstractmethod
    def init_schema(self) -> None: ...

    @abstractmethod
    def write_sources(self, rows: list[Source]) -> None: ...

    @abstractmethod
    def write_issuer_master(self, issuers, securities, listings, aliases) -> None: ...

    @abstractmethod
    def write_mentions(self, rows: list[Mention]) -> None: ...

    @abstractmethod
    def write_claims(self, rows: list[Claim]) -> None: ...

    @abstractmethod
    def write_analysis_results(self, rows: list[AnalysisResult]) -> None: ...

    # ---- market/connectivity layer (sectors, prices, macro) ----
    def write_sectors(self, rows) -> None: ...
    def write_macro(self, rows) -> None: ...
    def write_price_series(self, rows) -> None: ...

    def get_price_series_index(self) -> list[tuple[str, str, str]]:
        """(issuer_id, security_id, ticker) for every stored price series — the refresh
        input. ticker is the exact yfinance symbol used at first fetch (incl. .KS/.KQ)."""
        return []

    # ---- point-in-time reads (all filter knowledge_time <= as_of) ----
    @abstractmethod
    def get_active_universe(self, as_of: str) -> list[Issuer]:
        """Issuers that existed as-of T (survivorship: delisted-after-T still appear)."""

    @abstractmethod
    def resolve_alias(self, surface_form: str, as_of: str) -> list[tuple[str, str]]:
        """Return [(target_kind, target_id)] for aliases valid at `as_of`."""

    @abstractmethod
    def get_claims(self, as_of: str) -> list[Claim]: ...

    @abstractmethod
    def get_mentions(self, as_of: str) -> list[Mention]: ...

    @abstractmethod
    def get_sources(self) -> dict[str, Source]: ...

    @abstractmethod
    def get_analysis_results(self, as_of: str) -> list[AnalysisResult]: ...
