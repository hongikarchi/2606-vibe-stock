"""Bi-temporal conformance: SqliteRepository and Neo4jRepository must return IDENTICAL
results for the same as-of queries on identical seed data.

This retires the architecture review's only real worry about Neo4j — that point-in-time
("as-of") correctness could quietly diverge from SQLite. The seed is deliberately
BOUNDARY-RICH, and the as_of probes sit EXACTLY on each boundary, because the inclusive
`<=` vs exclusive `>` edges are where a lexical-string compare in one engine could drift
from the other.

Needs a live Neo4j (docker compose up -d). Skips cleanly if it's unavailable.

Run: pytest tests/test_neo4j_conformance.py
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as cfg
from skg.models import Alias, AnalysisResult, Claim, Issuer, Listing, Mention, Security, Source
from skg.store.sqlite_repo import SqliteRepository


# --------------------------------------------------------------- boundary-rich seed
ACTIVE = "1900-01-01T00:00:00"          # always-active sentinel
DELIST = "2023-06-30T00:00:00"          # ISS_DELIST stops being active AT this instant
SWITCH = "2008-09-01T00:00:00"          # $V flips Vivendi -> Visa AT this instant
FUTURE_KT = "2030-01-01T00:00:00"       # known only in the future relative to some probes


def _sources():
    return [Source("edgar", "EDGAR", "filing", "filing", 0.92, True),
            Source("anon", "anon", "anon", "anon", 0.10, False)]


def _issuer_master():
    issuers = [
        Issuer("ISS_ACTIVE", "ActiveCo", "listed", ACTIVE, None, ACTIVE),
        Issuer("ISS_DELIST", "DelistedCo", "delisted", ACTIVE, DELIST, ACTIVE),
        Issuer("ISS_FUTURE", "FutureCo", "listed", ACTIVE, None, FUTURE_KT),
    ]
    securities = [Security("SEC_A", "ISS_ACTIVE", "common")]
    listings = [Listing("L_A", "SEC_A", "ACT", "NYSE")]
    # the $V time-scoped pair: Vivendi until SWITCH (exclusive), Visa from SWITCH onward
    aliases = [
        Alias("$V", "en", "issuer", "ISS_VIVENDI", ACTIVE, SWITCH),
        Alias("$V", "en", "issuer", "ISS_VISA", SWITCH, None),
    ]
    return issuers, securities, listings, aliases


def _claims():
    def c(cid, kt):
        return Claim(
            claim_id=cid, doc_id="d", source_id="edgar", source_credibility=0.92,
            subject_id="ISS_ACTIVE", relation="sentiment", object_text="", claim_key="k",
            stance="neutral", source_span="x", span_start=0, span_end=1,
            event_time=kt, ingest_time=kt, knowledge_time=kt,
        )
    return [c("c1", ACTIVE), c("c2", DELIST), c("c3", FUTURE_KT)]


def _mentions():
    def m(mid, kt):
        return Mention(
            mention_id=mid, doc_id="d", source_id="edgar", surface_form="ActiveCo",
            resolved_target_id="ISS_ACTIVE", resolution_status="resolved",
            source_span="x", event_time=kt, ingest_time=kt, knowledge_time=kt,
        )
    return [m("m1", ACTIVE), m("m2", FUTURE_KT)]


def _analysis():
    return [AnalysisResult("ActiveCo", cfg.AS_OF_NOW, 0.1, 0.2, 2, 1, 1, 3, 0.9,
                           {"corroboration": "single-source"})]


def _seed(repo):
    repo.init_schema()
    repo.write_sources(_sources())
    repo.write_issuer_master(*_issuer_master())
    repo.write_claims(_claims())
    repo.write_mentions(_mentions())
    repo.write_analysis_results(_analysis())


# --------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def sqlite_repo(tmp_path_factory):
    db = tmp_path_factory.mktemp("conf") / "conf.db"
    repo = SqliteRepository(db)
    _seed(repo)
    yield repo
    repo.close()


@pytest.fixture(scope="module")
def neo4j_repo():
    # This fixture DETACH DELETEs the whole DB to isolate the test — the same DB the
    # accumulating loop fills. Guard it so a stray `pytest` can't silently destroy a
    # populated graph: opt in explicitly with SKG_ALLOW_NEO4J_WIPE=1.
    import os
    if os.environ.get("SKG_ALLOW_NEO4J_WIPE") != "1":
        pytest.skip("set SKG_ALLOW_NEO4J_WIPE=1 to run (this test wipes the Neo4j graph)")
    try:
        from neo4j import GraphDatabase
        from skg.store.neo4j_repo import Neo4jRepository
        drv = GraphDatabase.driver(cfg.NEO4J_URI, auth=(cfg.NEO4J_USER, cfg.NEO4J_PASSWORD))
        drv.verify_connectivity()
        drv.close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"live Neo4j unavailable: {e}")
    repo = Neo4jRepository(cfg.NEO4J_URI, cfg.NEO4J_USER, cfg.NEO4J_PASSWORD, cfg.NEO4J_DATABASE)
    repo.wipe()  # isolate from any loop-accumulated graph
    _seed(repo)
    yield repo
    repo.wipe()
    repo.close()


# as_of probes placed EXACTLY on each boundary
PROBES = [ACTIVE, DELIST, SWITCH, FUTURE_KT, cfg.AS_OF_NOW, cfg.AS_OF_PAST]


@pytest.mark.parametrize("as_of", PROBES)
def test_active_universe_matches(sqlite_repo, neo4j_repo, as_of):
    a = [(i.issuer_id, i.name, i.listing_status, i.status_valid_from,
          i.status_valid_to, i.knowledge_time) for i in sqlite_repo.get_active_universe(as_of)]
    b = [(i.issuer_id, i.name, i.listing_status, i.status_valid_from,
          i.status_valid_to, i.knowledge_time) for i in neo4j_repo.get_active_universe(as_of)]
    assert a == b, f"as_of={as_of}"


@pytest.mark.parametrize("as_of", PROBES)
def test_resolve_alias_matches(sqlite_repo, neo4j_repo, as_of):
    assert sqlite_repo.resolve_alias("$V", as_of) == neo4j_repo.resolve_alias("$V", as_of), \
        f"as_of={as_of}"


def test_alias_boundary_exclusive(sqlite_repo, neo4j_repo):
    """AT the switch instant, exclusive `>` on valid_to means $V resolves to Visa, not Vivendi."""
    for repo in (sqlite_repo, neo4j_repo):
        assert repo.resolve_alias("$V", SWITCH) == [("issuer", "ISS_VISA")]
    # one tick before, still Vivendi
    before = "2008-08-31T23:59:59"
    for repo in (sqlite_repo, neo4j_repo):
        assert repo.resolve_alias("$V", before) == [("issuer", "ISS_VIVENDI")]


def test_delisted_absent_at_boundary(sqlite_repo, neo4j_repo):
    """AT status_valid_to, the delisted issuer must be ABSENT (status_valid_to > as_of is false)."""
    for repo in (sqlite_repo, neo4j_repo):
        names = {i.issuer_id for i in repo.get_active_universe(DELIST)}
        assert "ISS_DELIST" not in names
    # one tick before, present
    before = "2023-06-29T23:59:59"
    for repo in (sqlite_repo, neo4j_repo):
        names = {i.issuer_id for i in repo.get_active_universe(before)}
        assert "ISS_DELIST" in names


@pytest.mark.parametrize("as_of", PROBES)
def test_get_claims_matches(sqlite_repo, neo4j_repo, as_of):
    a = sqlite_repo.get_claims(as_of)
    b = neo4j_repo.get_claims(as_of)
    assert [vars(c) for c in a] == [vars(c) for c in b], f"as_of={as_of}"


@pytest.mark.parametrize("as_of", PROBES)
def test_get_mentions_matches(sqlite_repo, neo4j_repo, as_of):
    a = sqlite_repo.get_mentions(as_of)
    b = neo4j_repo.get_mentions(as_of)
    assert [vars(m) for m in a] == [vars(m) for m in b], f"as_of={as_of}"


def test_get_sources_matches(sqlite_repo, neo4j_repo):
    a = {k: vars(v) for k, v in sqlite_repo.get_sources().items()}
    b = {k: vars(v) for k, v in neo4j_repo.get_sources().items()}
    assert a == b


def test_get_analysis_results_matches(sqlite_repo, neo4j_repo):
    a = sqlite_repo.get_analysis_results(cfg.AS_OF_NOW)
    b = neo4j_repo.get_analysis_results(cfg.AS_OF_NOW)
    assert [vars(r) for r in a] == [vars(r) for r in b]
