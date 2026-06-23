"""build_emergent.py — data-driven term network from news (no fixed themes).

    SKG_STORAGE_BACKEND=neo4j python build_emergent.py

Replaces the hand-picked 20-theme gazetteer. Reads all news text in the graph, removes only
language FUNCTION words, lets DOCUMENT FREQUENCY auto-demote generic words (korea/ceo/outlets),
and ranks survivors by co-occurrence connectivity — so "연결고리 많은 단어" rise into hubs
naturally as the data grows. Writes :Term nodes + (:Term)-[:CO_OCCURS]->(:Term).

Also attaches a descriptive TIME AXIS: per-term news volume by date (when an issue spiked).
This is OBSERVATION ONLY — no lead-lag / causal-precedence inference.
"""
from __future__ import annotations

import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze.emergent import build_term_network, tokens
from skg.store import make_repo


def _sparkline(counts_by_day: dict) -> str:
    """Tiny text sparkline of daily volume (descriptive 'when it spiked')."""
    if not counts_by_day:
        return ""
    days = sorted(counts_by_day)
    vals = [counts_by_day[d] for d in days]
    blocks = "▁▂▃▄▅▆▇█"
    hi = max(vals) or 1
    return "".join(blocks[min(len(blocks) - 1, int((v / hi) * (len(blocks) - 1)))] for v in vals)


def main() -> None:
    repo = make_repo(cfg)
    repo.init_schema()

    rows = repo._read(
        "MATCH (cl:Claim)-[:FROM_SOURCE]->(s:Source) WHERE cl.source_id STARTS WITH 'news::' "
        "RETURN cl.source_span AS text, cl.event_time AS t, s.source_id AS sid")

    # DATA-DRIVEN noise-outlet filter: automated stock-screener factories (simplywall, ChartMill,
    # MarketBeat, GuruFocus...) emit templated boilerplate (eps/estimates/therapeutics). Measure
    # each outlet's boilerplate ratio and DROP outlets above a threshold — objective, not a
    # hand-picked blocklist. We don't decide which TOPICS survive, only exclude content factories.
    BOILER = ("chartmill", "marketbeat", "therapeutics", "eps ", "estimates", "quantitative",
              "ad hoc", "gurufocus", "moomoo", "simply wall", "zacks", "benzinga",
              "seeking alpha", "insider monkey", "globenewswire", "globe and mail",
              "consensus", "price target", "analyst", "rating", "outperform", "dividend yield")
    from collections import Counter
    n_total, n_boiler = Counter(), Counter()
    for r in rows:
        if not r["text"]:
            continue
        sid = r["sid"]
        n_total[sid] += 1
        if any(b in r["text"].casefold() for b in BOILER):
            n_boiler[sid] += 1
    NOISE_RATIO = 0.55
    noise_outlets = {s for s in n_total if n_total[s] >= 10 and n_boiler[s] / n_total[s] >= NOISE_RATIO}
    texts = [r["text"] for r in rows if r["text"] and r["sid"] not in noise_outlets]
    dropped = sum(n_total[s] for s in noise_outlets)
    print(f"[emergent] dropped {len(noise_outlets)} automated-content outlets "
          f"({dropped} boilerplate articles); {len(texts)} real-journalism texts kept")

    terms, edges = build_term_network(texts, df_hi=0.02, df_lo=8, min_cooccur=5, top_terms=120)
    print(f"[emergent] {len(terms)} emergent hub terms, {len(edges)} co-occurrence edges")

    # TIME AXIS: per-term daily volume -> sparkline (descriptive only)
    term_set = {t["term"] for t in terms}
    by_term_day = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if not r["text"] or not r["t"] or r["sid"] in noise_outlets:
            continue
        day = r["t"][:10]
        for tk in tokens(r["text"]) & term_set:
            by_term_day[tk][day] += 1
    for t in terms:
        t["spark"] = _sparkline(by_term_day.get(t["term"], {}))

    repo.clear_terms()
    repo.write_terms(terms)
    repo.write_term_cooccurrence(edges)

    print("[emergent] top emergent hubs (rose from the data — no fixed list):")
    for t in terms[:20]:
        print(f"    {t['term']:18} 연결{t['degree']:3}  뉴스{t['df']:4}  {t['spark']}")
    print(f"[emergent] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
