"""Central configuration: credibility priors, thresholds, demo as-of dates, paths.

Single calibration surface — every magic number the pipeline uses lives here so the
research's "credibility taxonomy is load-bearing and must be auditable" point is honored.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent

# Load .env (KEY=VALUE per line) into os.environ so API keys persist across runs without
# living in code or git. Tiny loader — no python-dotenv dependency. Existing env wins.
_ENV = ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

FIXTURES = ROOT / "fixtures"
OUT = ROOT / "out"
DB_PATH = OUT / "skg.db"
VAULT = OUT / "vault"

# Real-data dirs live OUTSIDE `out/` so run.py's `rmtree(OUT)` never deletes the
# accumulated EDGAR corpus or the session-authored extractions.
REAL_CORPUS = ROOT / "data" / "edgar" / "corpus"
SESSION_EXTRACTIONS = ROOT / "data" / "edgar" / "extractions"
EDGAR_STATE = ROOT / "data" / "edgar" / "state.json"

# ---------------------------------------------------------------------------
# Storage backend — swap the Repository implementation without touching the pipeline.
# (research 01b "open storage spine"; user confirmed Neo4j as the spine.)
# ---------------------------------------------------------------------------
STORAGE_BACKEND = os.environ.get("SKG_STORAGE_BACKEND", "sqlite")  # "sqlite" | "neo4j"
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "skgpassword")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# ---------------------------------------------------------------------------
# Real-source ingest (EDGAR is key-free; DART needs a free key the user pastes)
# ---------------------------------------------------------------------------
# SEC asks for a contactable User-Agent ("app email"); without it data.sec.gov 403s.
EDGAR_USER_AGENT = os.environ.get("EDGAR_USER_AGENT", "archivibe-skg archivibe.sw.1@gmail.com")
DART_API_KEY = os.environ.get("DART_API_KEY", "")  # empty => DART fetcher disabled

# Loop goal: keep accumulating issuer/claim nodes until the graph reaches this size.
N_NODES_TARGET = int(os.environ.get("SKG_N_NODES_TARGET", "500"))

# ---------------------------------------------------------------------------
# Information time-decay — recent news is worth more (freshness, not prediction).
# A theme's "heat" = sum over its headlines of 0.5 ** (age_days / HALF_LIFE_DAYS), so a
# 2-week-old framing fades while this week's surfaces — the current narrative wins
# automatically. Half-life ~ the "이번주 vs 저번주" horizon the user described.
# ---------------------------------------------------------------------------
DECAY_HALF_LIFE_DAYS = float(os.environ.get("SKG_HALF_LIFE_DAYS", "10"))

# ---------------------------------------------------------------------------
# Market/connectivity layer (yfinance — key-free prices, FX, rates, commodities)
# ---------------------------------------------------------------------------
MARKET_ENABLED = os.environ.get("SKG_MARKET_ENABLED", "1") == "1"
PRICE_WINDOW_DAYS = int(os.environ.get("SKG_PRICE_WINDOW_DAYS", "90"))
# co-movement (corr) edges between prices and macro indicators are DEFERRED on purpose:
# a correlation-as-edge can read as a trading signal, which violates the no-signal stance.
# Structural edges (sector, has_price) carry the connectivity without that risk.
MARKET_COMOVEMENT_ENABLED = os.environ.get("SKG_COMOVEMENT_ENABLED", "0") == "1"
# how many issuers to pull prices for per market pass (yfinance is slower than EDGAR)
PRICE_MAX_ISSUERS = int(os.environ.get("SKG_PRICE_MAX_ISSUERS", "1500"))

# ---------------------------------------------------------------------------
# Source-credibility class priors  c(s) in [0, 1]
# (research 01b: regulator/filing high ... 종토방/anon low; folds into BOTH
#  PPR edge weights AND the TrustRank teleport vector)
# ---------------------------------------------------------------------------
CREDIBILITY_CLASS = {
    "regulator": 1.00,   # KRX / FSS / SEC actions
    "filing": 0.92,      # DART / EDGAR primary disclosures
    "major_news": 0.60,  # tier-1 press
    "analyst": 0.50,     # sell-side / research notes
    "whistleblower": 0.70,  # credible but unverified single source — deliberately mid/high
    "community": 0.20,   # 종토방 / Reddit boards
    "anon": 0.10,        # anonymous / throwaway
}
# Sources at or above this credibility count as "trusted" for provenance decomposition.
TRUSTED_THRESHOLD = 0.50

# ---------------------------------------------------------------------------
# Entity resolution thresholds (resolve.py)
# ---------------------------------------------------------------------------
RESOLVE = {
    "block_min": 80,       # rapidfuzz score floor to enter candidate list (0..100)
    "accept": 0.92,        # sim_1 must clear this to RESOLVE
    "margin": 0.10,        # sim_1 - sim_2 must clear this (else ambiguous -> ABSTAIN)
    "floor": 0.70,         # below this, no candidate -> PROVISIONAL
}

# ---------------------------------------------------------------------------
# Near-duplicate / effective-independence thresholds (prefilter.py, detectors.py)
# ---------------------------------------------------------------------------
NEAR_DUP_JACCARD = 0.80         # token-Jaccard >= this => same dup_group (prefilter)
NEAR_DUP_SIM = 0.85             # rapidfuzz token_set_ratio/100 >= this => copy edge (corroboration)
COORDINATION_WINDOW_MIN = 60    # mentions within N minutes on same target => coordinated (D2)

# ---------------------------------------------------------------------------
# Stance-dispersion threshold (detectors.py §5)
# ---------------------------------------------------------------------------
STANCE_SKEW_JSD = 0.20          # Jensen-Shannon divergence (base 2) flag threshold

# ---------------------------------------------------------------------------
# PageRank
# ---------------------------------------------------------------------------
PPR_ALPHA = 0.85

# ---------------------------------------------------------------------------
# Demo as-of dates — bi-temporal queries. "now" reconstructs the current universe;
# "past" demonstrates survivorship (a delisted issuer reappears in the past view).
# (Passed via SQL WHERE knowledge_time <= as_of; ISO-8601 strings sort lexically.)
# ---------------------------------------------------------------------------
AS_OF_NOW = "2026-06-23T00:00:00"
AS_OF_PAST = "2023-01-15T00:00:00"

# Guardrail: vocabulary that must NEVER appear in the exported vault (no trading signal).
FORBIDDEN_VOCAB = ["buy", "sell", "매수", "매도", "목표가", "price target", "strong buy"]
