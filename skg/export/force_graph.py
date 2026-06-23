"""force_graph.py — render a connected subgraph as an interactive force-directed HTML.

The Neo4j graph has 100k+ nodes; a browser physics engine dies above a few thousand. So we
render a BOUNDED, MEANINGFUL slice: the top-N issuers by credibility-weighted PageRank, plus
their sector nodes and the macro indicators. That is the colored-cluster web the user wants —
important hubs, colored by industry, connected through shared sector + market nodes — not an
unreadable 100k hairball.

  node color = SIC division (industry cluster)
  node size  = credibility-weighted PageRank (rank_credible)
  edges      = IN_SECTOR (clusters issuers) + HAS_PRICE + (issuer)-(macro via price)

Output: out/graph.html (self-contained, double-click to open). neo4j:5-community has no
Bloom/GDS, so this pyvis export is the pragmatic path to the Gephi-style image.
"""
from __future__ import annotations

from pathlib import Path

# Coarse SIC 2-digit division -> human label + color, for the cluster coloring.
# (SIC divisions: https://www.osha.gov/data/sic-manual)
_DIVISIONS = [
    (1, 9, "농림어업", "#6BCB77"),
    (10, 14, "광업", "#B5651D"),
    (15, 17, "건설", "#C19A6B"),
    (20, 39, "제조업", "#4D96FF"),
    (40, 49, "운수·통신·전기", "#9D4EDD"),
    (50, 51, "도매", "#00C2A8"),
    (52, 59, "소매", "#FF6B6B"),
    (60, 67, "금융·보험·부동산", "#FFD93D"),
    (70, 89, "서비스", "#FF9F45"),
    (90, 99, "공공행정", "#A0A0A0"),
]


def _division(sic_code: str) -> tuple[str, str]:
    """Return (division_label, color) for a SIC code, by its 2-digit major group."""
    try:
        mg = int(sic_code[:2])
    except (ValueError, TypeError):
        return ("기타", "#777777")
    for lo, hi, label, color in _DIVISIONS:
        if lo <= mg <= hi:
            return (label, color)
    return ("기타", "#777777")


def write_force_graph(repo, out_path: Path, as_of: str, top_n: int = 600) -> dict:
    """Build out/graph.html from the top-N issuers by PPR + sectors + macro. Returns a
    small summary dict. Reuses the repo's read methods (no new traversal logic here)."""
    from pyvis.network import Network

    # 1) PER-MARKET selection so BOTH markets are visible. KR issuers have ~0 credible PPR
    #    (news-only, no filing trust-seed mass), so a global top-N by PPR would show 0 KR.
    #    Take top US by PPR + ALL KR that have news coverage, sized by news count as a fallback.
    us = repo._read(
        "MATCH (a:AnalysisResult {as_of: $as_of}) MATCH (i:Issuer {name: a.entity_id}) "
        "WHERE i.issuer_id STARTS WITH 'CIK' "
        "RETURN a.entity_id AS name, a.ppr_credible AS ppr ORDER BY a.rank_credible LIMIT $n",
        as_of=as_of, n=top_n,
    )
    kr = repo._read(
        "MATCH (i:Issuer)<-[:ABOUT]-(cl:Claim) WHERE i.issuer_id STARTS WITH 'DART' "
        "RETURN i.name AS name, count(cl) AS news ORDER BY news DESC LIMIT 350"
    )
    names = [r["name"] for r in us] + [r["name"] for r in kr]
    ppr_of = {r["name"]: (r["ppr"] or 0.0) for r in us}
    # KR fallback size: scale news count into the same visual range as PPR-sized US nodes
    kr_news = {r["name"]: r["news"] for r in kr}
    if not names:
        names = [r["name"] for r in repo._read(
            "MATCH (i:Issuer) RETURN i.name AS name LIMIT $n", n=top_n)]

    net = Network(height="900px", width="100%", bgcolor="#0b0f1a", font_color="#e8e8e8",
                  notebook=False, directed=False)
    net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=120)

    sectors_seen: dict[str, str] = {}   # sector_id -> color
    macro_seen: set[str] = set()
    edges = 0

    # 2) for each top issuer: its node, sector node + edge, macro links via price exposure
    for name in names:
        rows = repo._read(
            "MATCH (i:Issuer {name: $name}) "
            "OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
            "OPTIONAL MATCH (i)-[:HAS_PRICE]->(p:PriceSeries) "
            "RETURN i.name AS iname, s.sector_id AS sid, s.name AS sname, "
            "s.sic_code AS sic, p.pct_change_window AS pct",
            name=name,
        )
        if not rows:
            continue
        r0 = rows[0]
        ppr = ppr_of.get(name, 0.0)
        if name in kr_news:
            size = 12 + min(kr_news[name], 40) * 0.8  # KR sized by news coverage (PPR is ~0)
        else:
            size = 12 + ppr * 4000  # US sized by credibility-weighted PageRank
        div_label, color = _division(r0["sic"] or "")
        net.add_node(f"I::{name}", label=name[:24], color=color,
                     size=max(8, min(size, 60)), title=f"{name}\n업종: {r0['sname'] or '?'}\nPPR={ppr:.4f}",
                     group=div_label)
        # sector node + edge
        if r0["sid"]:
            if r0["sid"] not in sectors_seen:
                _, scolor = _division(r0["sic"] or "")
                sectors_seen[r0["sid"]] = scolor
                net.add_node(f"S::{r0['sid']}", label=r0["sname"][:28], color=scolor,
                             shape="square", size=18, title=f"업종 클러스터: {r0['sname']}",
                             group=div_label)
            net.add_edge(f"I::{name}", f"S::{r0['sid']}", color="#33415544")
            edges += 1

    # 3) macro indicators as shared hub nodes (distinct shape, sized by news coverage so
    #    heavily-covered topics like rates/oil become prominent). Also connect any issuer in
    #    the view that shares news with a macro topic, so the macro layer links the clusters.
    macro_rows = repo._read(
        "MATCH (m:MacroIndicator) "
        "OPTIONAL MATCH (cl:Claim)-[:ABOUT]->(m) "
        "RETURN m.indicator_id AS id, m.name AS name, m.category AS cat, count(cl) AS news"
    )
    for m in macro_rows:
        boost = min(m["news"] or 0, 60)
        net.add_node(f"M::{m['id']}", label=m["name"], color="#FFFFFF", shape="star",
                     size=20 + boost * 0.6,
                     title=f"거시지표: {m['name']} ({m['cat']})\n뉴스 {m['news']}건",
                     group="거시지표")
        macro_seen.add(m["id"])

    # 4) co-movement edges (issuer -> macro hub) — the cross-market connective tissue.
    #    DESCRIPTIVE past correlation, NOT a signal; rendered dashed + labeled. This is what
    #    joins the US and KR blocks through the shared macro stars.
    name_set = set(names)
    como = 0
    for r in repo._read(
        "MATCH (i:Issuer)-[:HAS_PRICE]->(:PriceSeries)-[c:CO_MOVES_WITH]->(m:MacroIndicator) "
        "RETURN i.name AS issuer, m.indicator_id AS mid, c.corr AS corr"
    ):
        if r["issuer"] not in name_set:
            continue
        pos = r["corr"] >= 0
        net.add_edge(f"I::{r['issuer']}", f"M::{r['mid']}",
                     color="#5AC8FA66" if pos else "#FF6B6B66", dashes=True,
                     title=f"관측된 과거 상관 r={r['corr']:+.2f} (신호 아님)")
        como += 1
        edges += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path), notebook=False, open_browser=False)
    return {
        "issuers": len(names), "sectors": len(sectors_seen),
        "macro": len(macro_seen), "comovement_edges": como, "edges": edges, "path": str(out_path),
    }
