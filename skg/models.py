"""Dataclasses for the pipeline's domain objects.

These mirror the SQLite schema (see database/sqlite_repo.py). Kept as plain dataclasses
so they are trivially serializable and the storage layer stays a thin mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Source:
    source_id: str
    name: str
    source_type: str          # regulator | filing | major_news | analyst | whistleblower | community | anon
    credibility_class: str
    credibility: float
    is_trust_seed: bool = False


@dataclass
class Issuer:
    issuer_id: str            # authoritative key: DART corp_code / SEC CIK / LEI
    name: str
    listing_status: str = "listed"        # listed | delisted | merged
    status_valid_from: str = ""
    status_valid_to: str | None = None    # None = still valid
    knowledge_time: str = ""


@dataclass
class Security:
    security_id: str          # ISIN / share-class FIGI
    issuer_id: str
    share_class: str          # common | preferred


@dataclass
class Listing:
    listing_id: str           # venue / composite FIGI
    security_id: str
    ticker: str               # 005930 / 005935 / $V
    venue: str


@dataclass
class Alias:
    surface_form: str
    lang: str                 # ko | en
    target_kind: str          # issuer | security | listing
    target_id: str
    valid_from: str = ""
    valid_to: str | None = None


@dataclass
class Sector:
    """SIC industry sector (from SEC submissions). Connects issuer islands into clusters."""
    sector_id: str            # "SIC:3571"
    sic_code: str             # "3571"
    name: str                 # SEC sicDescription, e.g. "Electronic Computers"
    issuer_id: str            # the issuer this row links (one row per issuer-sector edge)
    event_time: str = ""
    knowledge_time: str = ""


@dataclass
class MacroIndicator:
    """A macro/market reference series (FX, rates, commodities, indices). One node per ticker."""
    indicator_id: str         # "MACRO:KRW=X"
    ticker: str               # "KRW=X"
    name: str                 # "USD/KRW 환율"
    category: str             # fx | rate | commodity | index | dollar_index
    last_close: float
    window_start: str
    window_end: str
    pct_change_window: float
    recent_closes_json: str   # bounded JSON array of recent daily closes
    event_time: str = ""
    knowledge_time: str = ""


@dataclass
class PriceSeries:
    """One node per issuer equity price (NOT one node per day). Bounded rolling window."""
    series_id: str            # "PX:AAPL.US"
    security_id: str          # "AAPL.US"
    issuer_id: str            # "CIK0000320193"
    ticker: str               # "AAPL"
    last_close: float
    window_start: str
    window_end: str
    pct_change_window: float
    vol_window: float         # annualized stdev of daily log-returns (descriptive)
    recent_closes_json: str   # bounded JSON array of recent daily closes
    returns_json: str         # bounded JSON array of daily log-returns
    event_time: str = ""
    knowledge_time: str = ""


@dataclass
class Document:
    """Raw ingested unit (after SampleReader)."""
    doc_id: str
    source_id: str
    lang: str
    text: str
    event_time: str
    ingest_time: str
    # filled in by prefilter
    dup_group_id: str | None = None
    is_amplifier: bool = False


@dataclass
class Claim:
    """A subject-relation-object assertion extracted from a document, with full provenance."""
    claim_id: str
    doc_id: str
    source_id: str
    source_credibility: float
    subject_id: str           # canonical entity id (or surface form if unresolved)
    relation: str             # supplies | competes_with | owns | guides_to | risk_flag | sentiment
    object_text: str
    claim_key: str            # canonicalized claim object for K-of-M grouping
    stance: str               # bullish | cautious | bearish | neutral
    source_span: str          # the cited substring — REQUIRED for grounding
    span_start: int
    span_end: int
    event_time: str
    ingest_time: str
    knowledge_time: str
    span_grounded: bool = True
    dup_group_id: str | None = None
    is_amplifier: bool = False
    superseded_by: str | None = None
    contradicts: str | None = None


@dataclass
class Mention:
    mention_id: str
    doc_id: str
    source_id: str
    surface_form: str
    resolved_target_id: str | None
    resolution_status: str    # resolved | provisional | naive_only
    source_span: str
    event_time: str
    ingest_time: str
    knowledge_time: str
    dup_group_id: str | None = None
    is_amplifier: bool = False


@dataclass
class AnalysisResult:
    entity_id: str
    as_of: str
    ppr_naive: float
    ppr_credible: float
    rank_naive: int
    rank_credible: int
    k_effective: int
    m_raw: int
    trusted_share: float
    flags: dict = field(default_factory=dict)
