"""reanalyze.py — recompute ranking + visualization over the LIVE graph (EDGAR + news).

run.py re-ingests a corpus; this instead reads the claims/sources ALREADY in Neo4j (which
now include news claims with real credibility variance) and recomputes credibility-weighted
PageRank -> :AnalysisResult, then regenerates out/graph.html. Use after news_pull.py so news
flows into the "TRUE over LOUD" ranking. Idempotent.

    SKG_STORAGE_BACKEND=neo4j python reanalyze.py
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze import pagerank
from skg.analyze.pagerank import ranked
from skg.export.force_graph import write_force_graph
from skg.models import AnalysisResult
from skg.store import make_repo
from skg.analyze.graph_builder import build_credible, build_naive


def main() -> None:
    repo = make_repo(cfg)
    as_of = cfg.AS_OF_NOW

    claims = repo.get_claims(as_of)
    sources = repo.get_sources()
    print(f"[reanalyze] {len(claims)} claims, {len(sources)} sources "
          f"(news outlets add credibility variance)")

    def keep(c):
        return not c.subject_id.startswith("provisional::") \
            and not (c.object_text or "").startswith("provisional::")
    claims = [c for c in claims if keep(c)]

    # Interpretable credibility metrics, read straight from the data (NOT via PPR — news
    # source nodes carry no teleport mass, so credibility variance shows up HERE, not in the
    # ranking). trusted_share = fraction of an entity's endorsement mass from trusted (>=0.5)
    # sources; m_raw = total endorsements; k_eff = effective-independent (dup-collapsed).
    from collections import defaultdict
    tot_mass, trust_mass = defaultdict(float), defaultdict(float)
    m_raw, groups = defaultdict(int), defaultdict(set)
    for c in claims:
        v = c.subject_id
        tot_mass[v] += c.source_credibility
        if c.source_credibility >= cfg.TRUSTED_THRESHOLD:
            trust_mass[v] += c.source_credibility
        m_raw[v] += 1
        groups[v].add(c.dup_group_id or f"solo_{c.claim_id}")
    trusted_share = {v: (trust_mass[v] / tot_mass[v] if tot_mass[v] else 0.0) for v in tot_mass}
    k_eff = {v: len(s) for v, s in groups.items()}

    g_naive = build_naive(claims)
    g_cred, seeds = build_credible(claims, sources)
    naive_scores = pagerank.naive_ppr(g_naive)
    cred_scores = pagerank.credible_ppr(g_cred, seeds)

    # rank ISSUERS among issuers only — macro indicators are a different node type (only
    # news endorsements, no trust-seed mass), so ranking them against issuers is meaningless.
    # Macro stays in the visual as hubs + via news-count, not the entity leaderboard.
    issuers = repo.get_active_universe(as_of)
    entity_ids = {i.issuer_id for i in issuers}
    name_of = {i.issuer_id: i.name for i in issuers}

    cred_entities = {n: s for n, s in cred_scores.items() if n in entity_ids}
    naive_entities = {n: s for n, s in naive_scores.items() if n in entity_ids}
    naive_rank = {n: rk for n, _, rk in ranked(naive_entities)}

    results = []
    for node, score, rk in ranked(cred_entities):
        results.append(AnalysisResult(
            entity_id=name_of.get(node, node), as_of=as_of,
            ppr_naive=naive_entities.get(node, 0.0), ppr_credible=score,
            rank_naive=naive_rank.get(node, 0), rank_credible=rk,
            k_effective=k_eff.get(node, 0), m_raw=m_raw.get(node, 0),
            trusted_share=round(trusted_share.get(node, 0.0), 3), flags={},
        ))
    repo.write_analysis_results(results)
    print(f"[reanalyze] wrote {len(results)} ranked entities")

    # HONEST credibility story: news barely moves the credible RANKING (news source nodes
    # carry no teleport mass + news claims add no relational edges — verified 10/10 top
    # unchanged when news excluded). Where news credibility DOES show: trusted_share, the
    # fraction of an entity's coverage mass from trusted (>=0.5) sources. Surface that.
    covered = [r for r in results if r.m_raw >= 3]
    low = sorted(covered, key=lambda r: r.trusted_share)[:5]
    print("[reanalyze] entities with the LEAST-trusted coverage (mostly aggregators/blogs):")
    for r in low:
        print(f"    {r.entity_id[:32]:32} trusted_share={r.trusted_share:.0%}  ({r.m_raw} endorsements)")

    summary = write_force_graph(repo, cfg.OUT / "graph.html", as_of, top_n=800)
    print(f"[reanalyze] graph.html: {summary['issuers']} issuers, "
          f"{summary['sectors']} sectors, {summary['macro']} macro hubs")
    repo.close()


if __name__ == "__main__":
    main()
