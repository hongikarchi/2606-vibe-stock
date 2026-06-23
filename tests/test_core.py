"""Core-algorithm unit tests — the contrasts ARE the product, so assert they fire.

Run: pytest   (or: python -m pytest)
"""
import sys
from pathlib import Path

import networkx as nx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skg.analyze import detectors, lexicon
from skg.analyze.pagerank import credible_ppr, naive_ppr, ranked
from skg.models import Claim, Source


def _claim(cid, src, cred, subj, obj="", dup=None, stance="neutral",
           relation="sentiment", span="x", grounded=True):
    return Claim(
        claim_id=cid, doc_id="d", source_id=src, source_credibility=cred,
        subject_id=subj, relation=relation, object_text=obj, claim_key="k",
        stance=stance, source_span=span, span_start=0, span_end=1,
        event_time="t", ingest_time="t", knowledge_time="t",
        span_grounded=grounded, dup_group_id=dup,
    )


# --------------------------------------------------------------- PPR: TRUE over LOUD
def test_credible_ppr_demotes_pump_below_filing():
    """Raw PageRank ranks a pump clique #1; credibility-weighted PPR must demote it."""
    from skg.store.graph_builder import build_credible, build_naive
    sources = {
        "dart": Source("dart", "DART", "filing", "filing", 0.92, True),
        "anon": Source("anon", "anon", "anon", "anon", 0.10, False),
    }
    # filing endorses TRUE_CO -> HANMI (structural); 5 anon posts endorse PUMP
    claims = [
        _claim("c1", "dart", 0.92, "TRUE_CO", obj="HANMI", relation="supplies"),
    ]
    for i in range(5):
        claims.append(_claim(f"p{i}", "anon", 0.10, "PUMP", dup="dup_pump"))

    g_n = build_naive(claims)
    g_c, seeds = build_credible(claims, sources)
    naive = {n: rk for n, _, rk in ranked(naive_ppr(g_n))}
    cred = {n: rk for n, _, rk in ranked(credible_ppr(g_c, seeds))}

    # naive: PUMP gets the most endorsement edges -> ranks ahead of TRUE_CO
    assert naive["PUMP"] < naive["TRUE_CO"], naive
    # credible: trust teleport floods the filing side -> PUMP demoted below TRUE_CO
    assert cred["PUMP"] > cred["TRUE_CO"], cred


def test_ranked_is_deterministic_on_ties():
    scores = {"b": 0.5, "a": 0.5, "c": 0.1}
    r = ranked(scores)
    assert [n for n, _, _ in r] == ["a", "b", "c"]  # tie broken by node id


# --------------------------------------------------------------- entity resolution
def test_naive_resolve_overcounts_vs_canonical():
    from skg.resolve import naive_resolve
    # four surface forms of ONE entity -> naive sees 4 nodes
    assert naive_resolve(["삼성전자", "Samsung Electronics", "삼전", "005930"]) == 4


# --------------------------------------------------------------- effective-independent
def test_k_of_m_collapses_pump():
    claims = [_claim(f"p{i}", "anon", 0.1, "PUMP", dup="dup_pump") for i in range(5)]
    out = detectors.effective_independent(claims)
    assert len(out) == 1
    rec = out[0]
    assert rec["m_raw"] == 5 and rec["k_effective"] == 1
    assert "상한" in rec["label"]  # K labeled as upper bound on independence


# --------------------------------------------------------------- stance + grounding
def test_stance_lexicon_classifies_cautionary_as_bearish():
    assert lexicon.stance_of("분기 매출이 시장 기대에 미치지 못했다") == "bearish"
    assert lexicon.stance_of("신규 장비 수주는 호재로 작용할 수 있다") == "bullish"


def test_grounding_flags_polarity_inversion():
    # span DENIES bankruptcy; claim asserts it as a bearish risk fact -> flagged
    c = _claim("c1", "news", 0.6, "SKH", relation="risk_flag", stance="bearish",
               span="파산 우려는 사실무근이라고 부인했다")
    flags = detectors.grounding([c])
    assert len(flags) == 1 and flags[0]["issue"] == "polarity-inverted"


def test_grounding_passes_clean_claim():
    c = _claim("c1", "dart", 0.92, "SEC", relation="supplies", stance="neutral",
               span="삼성전자가 HBM을 공급한다")
    assert detectors.grounding([c]) == []


# --------------------------------------------------------------- JSD
def test_jsd_zero_for_identical_and_high_for_disjoint():
    assert detectors._jsd([0.5, 0.5, 0.0], [0.5, 0.5, 0.0]) == pytest.approx(0.0)
    # fully disjoint distributions -> JSD = 1.0 (base 2)
    assert detectors._jsd([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)
