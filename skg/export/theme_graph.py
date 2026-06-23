"""theme_graph.py — a READABLE theme-association view (out/themes.html).

Not another 800-dot company hairball. A few dozen labeled THEME nodes, sized by how often
they appear in the news, connected by weighted co-occurrence edges (thicker = appear together
more). Each theme optionally shows its few top anchored entities. This is the substrate the
user wanted to reason over: pick 반도체, see it links to AI, 데이터센터, 공급망, 삼성전자 —
and trace the story yourself. Every edge is OBSERVED CO-OCCURRENCE, never asserted causation.
"""
from __future__ import annotations

from pathlib import Path

# theme_id -> color by rough domain, so related themes read as a family
_THEME_COLOR = {
    "ai": "#4D96FF", "semiconductor": "#5AC8FA", "datacenter": "#7B61FF", "power_energy": "#FFD93D",
    "ev_battery": "#6BCB77", "supply": "#00C2A8",
    "rates": "#FF9F45", "fx": "#FF6B6B", "inflation": "#FF8C42", "gold": "#E8C547",
    "oil": "#C19A6B",
    "trump": "#FF5C8A", "geopolitics": "#E84855", "trade": "#F26430", "defense": "#9D4EDD",
    "regulation": "#A0A0A0",
    "earnings": "#22C55E", "ma": "#14B8A6", "realestate": "#94A3B8", "crypto": "#F59E0B",
}


def write_theme_graph(repo, out_path: Path, top_entities_per_theme: int = 3) -> dict:
    from pyvis.network import Network

    net = Network(height="900px", width="100%", bgcolor="#0b0f1a", font_color="#f0f0f0",
                  notebook=False, directed=False)
    net.barnes_hut(gravity=-12000, central_gravity=0.4, spring_length=180, spring_strength=0.02)

    themes = repo._read("MATCH (t:Theme) RETURN t.theme_id AS id, t.label AS label, t.freq AS freq")
    if not themes:
        raise RuntimeError("no :Theme nodes — run build_themes.py first")
    maxf = max((t["freq"] or 1) for t in themes)
    for t in themes:
        size = 18 + 42 * ((t["freq"] or 0) / maxf)   # big, readable theme hubs
        net.add_node(f"T::{t['id']}", label=t["label"], shape="dot",
                     color=_THEME_COLOR.get(t["id"], "#888"), size=size,
                     title=f"{t['label']} — 뉴스 {t['freq']}건", font={"size": 22})

    # co-occurrence edges, thickness ~ weight (the association strength)
    edges = repo._read(
        "MATCH (a:Theme)-[e:CO_OCCURS]->(b:Theme) "
        "RETURN a.theme_id AS a, b.theme_id AS b, e.weight AS w ORDER BY e.weight DESC")
    maxw = max((e["w"] or 1) for e in edges) if edges else 1
    for e in edges:
        net.add_edge(f"T::{e['a']}", f"T::{e['b']}", value=e["w"], width=1 + 8 * (e["w"] / maxw),
                     color="#88aadd55", title=f"같은 헤드라인 {e['w']}건 동시 등장")

    # a few top anchored entities per theme (so themes touch concrete companies)
    ent_added = set()
    n_ent_edges = 0
    for t in themes:
        rows = repo._read(
            "MATCH (t:Theme {theme_id: $tid})-[x:MENTIONED_WITH]->(e) "
            "RETURN coalesce(e.name, e.indicator_id) AS name, "
            "       coalesce(e.issuer_id, e.indicator_id) AS id, x.weight AS w "
            "ORDER BY x.weight DESC LIMIT $k", tid=t["id"], k=top_entities_per_theme)
        for r in rows:
            if not r["name"]:
                continue
            nid = f"E::{r['id']}"
            if nid not in ent_added:
                net.add_node(nid, label=r["name"][:18], shape="box", color="#2a3550",
                             size=10, font={"size": 12, "color": "#bbb"},
                             title=f"{r['name']}  (이 테마 뉴스 {r['w']}건)")
                ent_added.add(nid)
            net.add_edge(f"T::{t['id']}", nid, color="#33415533", width=1)
            n_ent_edges += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path), notebook=False, open_browser=False)
    return {"themes": len(themes), "cooccur_edges": len(edges),
            "entities": len(ent_added), "entity_edges": n_ent_edges, "path": str(out_path)}
