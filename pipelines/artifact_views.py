"""artifact_views.py — extract each view's DATA (not HTML) for the React frontend.

Reuses the existing build logic where possible; returns plain dicts the React app renders.
Keeping data-extraction here (build-time, Neo4j) means the frontend never touches the DB.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import json

import config as cfg


# ---------------------------------------------------------------- themes
def build_theme_data(repo) -> dict:
    """Single source of truth: build_theme_view.compute_theme_data assembles the
    {nodes, edges, summary_date} structure used by BOTH the HTML builder and this React
    artifact (no more regex-scraping JSON back out of themes.html)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_btv", _pathlib.Path(__file__).resolve().parent / "build_theme_view.py")
    btv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(btv)
    return btv.compute_theme_data(repo)


# ---------------------------------------------------------------- dashboard
def build_dashboard_data(repo) -> dict:
    """Market-state data: breadth (US/KR), commodities+series, hot/cold sectors, top terms."""
    from skg.export.dashboard import _ksic_name

    def breadth(prefix):
        rows = repo._read(
            f"MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH '{prefix}' AND i.pos_52w IS NOT NULL "
            "RETURN i.pos_52w AS p")
        vals = [r["p"] for r in rows]
        if not vals:
            return None
        n = len(vals)
        return {"n": n, "hi": round(100 * sum(v >= 80 for v in vals) / n, 1),
                "lo": round(100 * sum(v <= 20 for v in vals) / n, 1),
                "med": round(sorted(vals)[n // 2], 1)}

    macros = [dict(r) for r in repo._read(
        "MATCH (m:MacroIndicator) RETURN m.name AS name, m.last_close AS px, "
        "m.pct_change_window AS chg, m.category AS cat, m.recent_closes_json AS series, "
        "m.window_end AS end "
        "ORDER BY m.category, m.name")]
    for m in macros:
        try:
            m["series"] = json.loads(m.get("series") or "[]")
        except Exception:  # noqa: BLE001
            m["series"] = []
        # window-end date ships with the artifact so the gate can verify label==content
        m["end"] = str(m.get("end") or "")[:10]

    sectors_raw = repo._read(
        "MATCH (i:Issuer)-[:IN_SECTOR]->(s:Sector) WHERE i.pos_52w IS NOT NULL "
        "WITH s.sector_id AS sid, s.name AS name, s.sic_code AS code, "
        "avg(i.pos_52w) AS heat, count(i) AS n WHERE n >= 4 "
        "RETURN sid, name, code, heat, n ORDER BY heat DESC")
    sectors = []
    for s in sectors_raw:
        label = _ksic_name(s["code"]) if str(s["sid"]).startswith("KSIC") else s["name"]
        sectors.append({"sector": label, "heat": round(s["heat"], 1), "n": s["n"]})

    terms = [dict(r) for r in repo._read(
        "MATCH (t:Term) RETURN t.term AS term, t.degree AS deg, t.spark AS spark "
        "ORDER BY t.degree DESC LIMIT 16")]
    return {"as_of": cfg.AS_OF_NOW, "us": breadth("CIK"), "kr": breadth("DART"),
            "macros": macros, "hot": sectors[:8], "cold": sectors[-8:][::-1], "terms": terms}


# ---------------------------------------------------------------- emergent
def build_emergent_data(repo) -> dict:
    """Data-driven term network with community clusters (networkx)."""
    import networkx as nx
    terms = [dict(r) for r in repo._read(
        "MATCH (t:Term) RETURN t.term AS term, t.df AS df, t.degree AS deg, t.spark AS spark")]
    edges = [dict(r) for r in repo._read(
        "MATCH (a:Term)-[e:CO_OCCURS]->(b:Term) RETURN a.term AS a, b.term AS b, e.weight AS w")]
    g = nx.Graph()
    for t in terms:
        g.add_node(t["term"])
    for e in edges:
        g.add_edge(e["a"], e["b"], weight=e["w"])
    cluster = {}
    try:
        for i, c in enumerate(nx.community.greedy_modularity_communities(g, weight="weight")):
            for node in c:
                cluster[node] = i
    except Exception:  # noqa: BLE001
        pass
    for t in terms:
        t["cluster"] = cluster.get(t["term"], 0)
    return {"terms": terms, "edges": edges, "clusters": len(set(cluster.values()))}


# ---------------------------------------------------------------- graph (issuers)
def build_graph_data(repo, top_n: int = 400, kr_slots: int = 120) -> dict:
    """Top issuers + sectors + macro hubs, EACH enriched for drill-down. RESERVES slots for
    both markets: top US by credibility-weighted PageRank (rank_credible) AND top KR by NAIVE
    PageRank (ppr_naive) — KR is structurally ~0 on rank_credible because credibility is
    US-press-based, so credible-rank would otherwise hide every Korean company. (company lens,
    parallel to themes' issue lens — click a company, see its story.)"""
    from skg.analyze.themes import label_of, themes_in
    from skg.analyze import lexicon
    from skg.sources.news import is_quality_outlet

    import json as _json
    cols = ("a.entity_id AS name, a.ppr_credible AS ppr, a.rank_credible AS rank, "
            "i.issuer_id AS iid, i.pos_52w AS pos, s.sector_id AS sid, s.name AS sector, "
            "s.sic_code AS sic, i.ratings_consensus AS rc, i.ratings_changes AS rch")
    us_rows = repo._read(
        "MATCH (a:AnalysisResult {as_of:$as_of}) MATCH (i:Issuer {name:a.entity_id}) "
        "WHERE i.issuer_id STARTS WITH 'CIK' OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
        f"RETURN {cols} ORDER BY a.rank_credible LIMIT $n",
        as_of=cfg.AS_OF_NOW, n=max(0, top_n - kr_slots))
    # KR slots: rank by NEWS COVERAGE (count of news Claims), not ppr_naive. ppr_naive is a
    # pure link-structure score that buried the KOSPI bellwethers (SK하이닉스/NAVER/삼성바이오/
    # POSCO all ranked outside the top slots while quiet caps 한국가스공사/펄어비스 took them).
    # Market cap isn't stored on KR Issuer nodes (no mktcap property), so news-degree is the
    # available, reversible proxy for "companies the market is actually talking about". It
    # surfaces SK하이닉스 (the HBM/AI bellwether) at #1, fixing the named coverage defect.
    kr_rows = repo._read(
        "MATCH (a:AnalysisResult {as_of:$as_of}) MATCH (i:Issuer {name:a.entity_id}) "
        "WHERE i.issuer_id STARTS WITH 'DART' OPTIONAL MATCH (i)-[:IN_SECTOR]->(s:Sector) "
        "OPTIONAL MATCH (i)<-[:ABOUT]-(cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
        f"WITH a, i, s, count(cl) AS news_n "
        f"RETURN {cols}, news_n ORDER BY news_n DESC, a.ppr_naive DESC LIMIT $n",
        as_of=cfg.AS_OF_NOW, n=kr_slots)
    issuers = [dict(r) for r in us_rows] + [dict(r) for r in kr_rows]
    for i in issuers:
        i.pop("news_n", None)  # ranking-only column (KR query); not part of the node payload
    iids = [i["iid"] for i in issuers]

    # per-issuer news headlines (drill-down evidence) — exclude junk (factory) outlets
    news = repo._read(
        "MATCH (i:Issuer)<-[:ABOUT]-(cl:Claim)-[:FROM_SOURCE]->(src:Source) "
        "WHERE i.issuer_id IN $iids AND cl.source_id STARTS WITH 'news::' "
        "RETURN i.issuer_id AS iid, cl.source_span AS h, cl.event_time AS t, src.name AS outlet",
        iids=iids)
    by_issuer = {}
    for r in news:
        h = r["h"]
        if not h or not is_quality_outlet(r["outlet"]):  # surface only vetted press
            continue
        st = lexicon.stance_of(h)
        ch = (h.split(" - ")[0] if " - " in h[-40:] else h).strip()[:110]
        by_issuer.setdefault(r["iid"], []).append(((r["t"] or "")[:10], ch, st))

    # sector members (peers) — for "same-sector companies"
    peers = {}
    for r in repo._read(
        "MATCH (i:Issuer)-[:IN_SECTOR]->(s:Sector)<-[:IN_SECTOR]-(p:Issuer) "
        "WHERE i.issuer_id IN $iids AND p.issuer_id <> i.issuer_id "
        "RETURN i.issuer_id AS iid, collect(DISTINCT p.name)[..6] AS peers", iids=iids):
        peers[r["iid"]] = r["peers"]

    for i in issuers:
        hs = by_issuer.get(i["iid"], [])
        # stance breakdown
        sc = {"bull": 0, "bear": 0, "neut": 0}
        themes = {}
        for _, h, st in hs:
            sc["bull" if st == "bullish" else "bear" if st == "bearish" else "neut"] += 1
            for th in themes_in(h):
                themes[th] = themes.get(th, 0) + 1
        # top headlines: stance-bearing first, then recent
        hs_sorted = sorted(hs, reverse=True)
        stanced = [{"d": d, "t": h, "s": s} for d, h, s in hs_sorted if s != "neutral"][:6]
        neutral = [{"d": d, "t": h, "s": s} for d, h, s in hs_sorted if s == "neutral"]
        i["news_count"] = len(hs)
        i["stance"] = sc
        i["heads"] = stanced + neutral[: max(0, 6 - len(stanced))]
        i["themes"] = [{"id": t, "label": label_of(t), "n": n}
                       for t, n in sorted(themes.items(), key=lambda x: -x[1])[:5]]
        i["peers"] = peers.get(i["iid"], [])
        # analyst ratings (관측·추천 아님) — parse the JSON stamped on the node
        try:
            i["ratings"] = {"consensus": _json.loads(i.pop("rc")) if i.get("rc") else None,
                            "changes": _json.loads(i.pop("rch")) if i.get("rch") else []}
        except Exception:  # noqa: BLE001
            i["ratings"] = None
        i.pop("rc", None); i.pop("rch", None)

    macros = [dict(r) for r in repo._read(
        "MATCH (m:MacroIndicator) OPTIONAL MATCH (cl:Claim)-[:ABOUT]->(m) "
        "RETURN m.indicator_id AS id, m.name AS name, m.category AS cat, count(cl) AS news")]
    return {"issuers": issuers, "macros": macros}
