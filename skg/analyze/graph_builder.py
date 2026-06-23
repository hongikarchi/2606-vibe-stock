"""graph_builder — turn repository claims into a networkx.DiGraph.

Graph model (per research "TrustRank teleport seeded on filing/regulator SOURCE nodes"):
  Nodes  = canonical entities  ∪  source_ids
  Edges  = source -> subject_entity   (endorsement/attention; weight = source credibility)
         + subject_entity -> object_entity   (relational claim; carries structural info)
  Teleport seeds (credible PPR) = trust-seed SOURCES (dart/krx/edgar), never subjects.

THE pump-loses mechanism is driven by teleport: anon/community sources get ZERO restart
mass while restart floods the filing sources, so a thinly-sourced pump target collapses.
Edge namespaces are uniform: every endpoint is a canonical id (subject_id already is; the
object is resolved to a canonical id by run.py before building, falling back to a stable
``entity::<surface>`` key so subject- and object-mentions of one entity are the SAME node).

build() returns both the naive control graph and the credible graph + seed set, computed
from the SAME claims so the contrast is apples-to-apples.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from ..models import Claim, Source


def build_naive(claims: list[Claim]) -> nx.DiGraph:
    """Control graph: unit-weight source->subject + subject->object edges, uniform teleport."""
    g = nx.DiGraph()
    for c in claims:
        # endorsement: source attests to subject
        _add(g, c.source_id, c.subject_id, 1.0)
        if c.object_text:
            _add(g, c.subject_id, c.object_text, 1.0)
    return g


def build_credible(claims: list[Claim], sources: dict[str, Source]) -> tuple[nx.DiGraph, set[str]]:
    """Credibility-weighted graph + trust-seed SOURCE nodes.

    Endorsement edges from one effective-independent group collapse to a single
    credibility-weighted contribution (so 5 copy-paste pump posts != 5x weight).
    """
    g = nx.DiGraph()
    trust_seeds: set[str] = set()

    # collapse endorsements: (source, subject) keyed by dup_group -> max credibility
    endorse: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    relational: dict[tuple[str, str], float] = defaultdict(float)

    for c in claims:
        src = sources.get(c.source_id)
        cred = c.source_credibility
        key = c.dup_group_id or f"solo_{c.claim_id}"
        prev = endorse[(c.source_id, c.subject_id)].get(key, 0.0)
        endorse[(c.source_id, c.subject_id)][key] = max(prev, cred)
        if c.object_text:
            relational[(c.subject_id, c.object_text)] += cred
        if src and src.is_trust_seed:
            trust_seeds.add(c.source_id)

    for (s, subj), groups in endorse.items():
        _add(g, s, subj, sum(groups.values()))
    for (subj, obj), w in relational.items():
        _add(g, subj, obj, w)

    for s in trust_seeds:
        if s not in g:
            g.add_node(s)
    return g, trust_seeds


def _add(g: nx.DiGraph, u: str, v: str, w: float) -> None:
    if not u or not v:
        return
    if g.has_edge(u, v):
        g[u][v]["weight"] += w
    else:
        g.add_edge(u, v, weight=w)
