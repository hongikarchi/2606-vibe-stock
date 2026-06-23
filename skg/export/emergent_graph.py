"""emergent_graph.py — readable view of the data-driven term network (out/emergent.html).

The hand-picked themes are gone; these nodes ROSE FROM THE DATA (DF-filtered, ranked by
connectivity). Node size = how connected a term is (the hubs the user wanted). Edge width =
co-occurrence strength. Color = graph community (networkx greedy modularity) so related terms
read as a family — clusters emerge instead of being declared. Hover shows the time sparkline.
Observation only; the human reads the web and infers the story.
"""
from __future__ import annotations

from pathlib import Path

_PALETTE = ["#4D96FF", "#FF6B6B", "#6BCB77", "#FFD93D", "#9D4EDD", "#00C2A8", "#FF9F45",
            "#5AC8FA", "#F26430", "#E84855", "#14B8A6", "#F59E0B", "#7B61FF", "#22C55E"]


def write_emergent_graph(repo, out_path: Path) -> dict:
    import networkx as nx
    from pyvis.network import Network

    terms = repo._read("MATCH (t:Term) RETURN t.term AS term, t.df AS df, t.degree AS deg, t.spark AS spark")
    if not terms:
        raise RuntimeError("no :Term nodes — run build_emergent.py first")
    edges = repo._read("MATCH (a:Term)-[e:CO_OCCURS]->(b:Term) RETURN a.term AS a, b.term AS b, e.weight AS w")

    # detect communities so related terms share a color (clusters emerge from structure)
    g = nx.Graph()
    for t in terms:
        g.add_node(t["term"])
    for e in edges:
        g.add_edge(e["a"], e["b"], weight=e["w"])
    color_of = {}
    try:
        comms = nx.community.greedy_modularity_communities(g, weight="weight")
        for i, c in enumerate(comms):
            for node in c:
                color_of[node] = _PALETTE[i % len(_PALETTE)]
    except Exception:  # noqa: BLE001
        pass

    net = Network(height="900px", width="100%", bgcolor="#0b0f1a", font_color="#f0f0f0",
                  notebook=False, directed=False)
    net.barnes_hut(gravity=-14000, central_gravity=0.35, spring_length=160, spring_strength=0.02)

    maxdeg = max((t["deg"] or 1) for t in terms)
    for t in terms:
        size = 14 + 40 * ((t["deg"] or 0) / maxdeg)
        spark = t["spark"] or ""
        net.add_node(t["term"], label=t["term"], size=size,
                     color=color_of.get(t["term"], "#888"),
                     title=f"{t['term']}\n연결 {t['deg']}개 · 뉴스 {t['df']}건\n시간추이 {spark}",
                     font={"size": 18})
    maxw = max((e["w"] or 1) for e in edges) if edges else 1
    for e in edges:
        net.add_edge(e["a"], e["b"], value=e["w"], width=1 + 7 * (e["w"] / maxw),
                     color="#8899bb44", title=f"같은 기사 {e['w']}건 동시 등장")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path), notebook=False, open_browser=False)
    n_comm = len(set(color_of.values()))
    return {"terms": len(terms), "edges": len(edges), "clusters": n_comm, "path": str(out_path)}
