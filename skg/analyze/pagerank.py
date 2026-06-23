"""PageRank — naive (control) vs credibility-weighted Personalized-PageRank + TrustRank.

Credibility folds in at BOTH places (research 02b §2):
  (a) edge weights — already credibility-scaled in graph_builder.build_credible
  (b) teleport / personalization — restart mass lands only on trust-seed (filing) nodes
      (TrustRank). Uniform teleport would re-introduce LOUD-over-TRUE, so we never use it
      for the credible variant.

Determinism: rank ties broken by (-score, node_id) so the vault is byte-identical.
"""
from __future__ import annotations

import networkx as nx

import config as cfg


def naive_ppr(g: nx.DiGraph) -> dict[str, float]:
    """Control: unit weights, uniform teleport (vanilla PageRank)."""
    if g.number_of_nodes() == 0:
        return {}
    return nx.pagerank(g, alpha=cfg.PPR_ALPHA, weight="weight",
                       tol=1e-10, max_iter=300)


def credible_ppr(g: nx.DiGraph, trust_seeds: set[str]) -> dict[str, float]:
    """Credibility-weighted PPR with TrustRank teleport seeded on filing/regulator nodes."""
    if g.number_of_nodes() == 0:
        return {}
    nodes = list(g.nodes())
    seeds = [n for n in nodes if n in trust_seeds]
    if seeds:
        p = {n: (1.0 if n in trust_seeds else 0.0) for n in nodes}
        total = sum(p.values())
        p = {n: v / total for n, v in p.items()}
    else:
        # fallback: credibility-proportional teleport via weighted in-degree (never uniform)
        wdeg = {n: max(g.in_degree(n, weight="weight"), 1e-9) for n in nodes}
        total = sum(wdeg.values())
        p = {n: w / total for n, w in wdeg.items()}
    return nx.pagerank(g, alpha=cfg.PPR_ALPHA, weight="weight",
                       personalization=p, dangling=p, tol=1e-10, max_iter=300)


def ranked(scores: dict[str, float]) -> list[tuple[str, float, int]]:
    """Return [(node, score, rank)] with deterministic (-score, node_id) tie-break."""
    order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(node, score, i + 1) for i, (node, score) in enumerate(order)]
