"""news_pull.py — fetch news (two-track) and connect it into the live graph. MANUAL run.

    SKG_STORAGE_BACKEND=neo4j python news_pull.py

Track A: company news for the top-N issuers by PageRank -> (:Claim)-[:ABOUT]->(:Issuer)
Track B: macro-topic news (oil/Fed/USD-KRW/gold...) -> (:Claim)-[:ABOUT]->(:MacroIndicator)

The subject is known (we queried by entity), so claims are built with the KNOWN subject_id
directly — no name-resolution guesswork. Per-outlet sources are registered with credibility
mapped off the article's outlet (tier-1 press 0.60 vs aggregator/blog 0.20) — the first
credibility VARIANCE in the graph, which makes "TRUE over LOUD" ranking meaningful.

Idempotent: doc_id is URL-derived and all writes MERGE, so re-running accumulates without
duplicating. Syndicated wire stories collapse via the existing prefilter (dup_group).
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg import prefilter
from skg.extract.news_rules import extract_from_headline
from skg.models import Claim, Document, Mention, Source
from skg.sources.news import MACRO_TOPICS, NewsFetcher
from skg.store import make_repo

TOP_N = int(__import__("os").environ.get("SKG_NEWS_TOP_N", "500"))


def _docs_from(raw: list[dict]) -> list[Document]:
    return [Document(d["doc_id"], d["source_id"], d["lang"], d["text"],
                     d["event_time"], d["ingest_time"]) for d in raw]


def main() -> None:
    repo = make_repo(cfg)
    as_of = cfg.AS_OF_NOW
    fetcher = NewsFetcher()

    # top-N issuers by credibility-weighted PageRank (already computed in :AnalysisResult)
    top = repo._read(
        "MATCH (a:AnalysisResult {as_of:$as_of}) RETURN a.entity_id AS name "
        "ORDER BY a.rank_credible LIMIT $n", as_of=as_of, n=TOP_N)
    # map display name -> issuer_id via the live graph
    name_rows = repo._read("MATCH (i:Issuer) RETURN i.name AS name, i.issuer_id AS iid")
    id_of = {r["name"]: r["iid"] for r in name_rows}
    targets = [(id_of[r["name"]], r["name"]) for r in top if r["name"] in id_of]
    print(f"[news] top {len(targets)} issuers + {len(MACRO_TOPICS)} macro topics")

    raw_docs: list[dict] = []
    # Track A — company news
    for i, (iid, name) in enumerate(targets):
        raw_docs.extend(fetcher.fetch_company_news(iid, name, as_of))
        if (i + 1) % 100 == 0:
            print(f"[news] company {i+1}/{len(targets)}  docs so far={len(raw_docs)}")
    # Track B — macro/international news
    macro_docs = fetcher.fetch_macro_news(as_of)
    raw_docs.extend(macro_docs)
    print(f"[news] fetched {len(raw_docs)} articles ({len(macro_docs)} macro)")

    # dedup syndicated wire stories (same prefilter the pump-detection uses)
    docs = prefilter.run(_docs_from(raw_docs))
    by_id = {d.doc_id: d for d in docs}
    dup_groups = {d.dup_group_id for d in docs if d.dup_group_id}
    amps = sum(1 for d in docs if d.is_amplifier)
    print(f"[news] dedup: {len(dup_groups)} syndication group(s), {amps} amplifier(s) collapsed")

    # register per-outlet sources (credibility variance!)
    seen_src: dict[str, Source] = {}
    for rd in raw_docs:
        sid = rd["source_id"]
        if sid not in seen_src:
            seen_src[sid] = Source(sid, rd["_outlet"], "major_news" if rd["_cred"] >= 0.5 else "community",
                                   rd["_cred_class"], rd["_cred"], is_trust_seed=False)
    repo.write_sources(list(seen_src.values()))
    print(f"[news] {len(seen_src)} distinct outlets registered (credibility 0.20–0.60)")

    # build claims with KNOWN subjects (issuer_id or macro indicator_id)
    claims, mentions = [], []
    for rd in raw_docs:
        doc = by_id.get(rd["doc_id"])
        if doc is None:
            continue
        res = extract_from_headline(doc, rd["_subject_surface"])
        cred = rd["_cred"]
        for idx, ec in enumerate(res.claims):
            claims.append(Claim(
                claim_id=f"{doc.doc_id}#c{idx}", doc_id=doc.doc_id, source_id=doc.source_id,
                source_credibility=cred, subject_id=rd["_subject_id"], relation=ec.relation,
                object_text="", claim_key=ec.claim_key, stance=ec.stance,
                source_span=ec.source_span, span_start=ec.span_start, span_end=ec.span_end,
                event_time=doc.event_time, ingest_time=doc.ingest_time,
                knowledge_time=doc.ingest_time, dup_group_id=doc.dup_group_id,
                is_amplifier=doc.is_amplifier,
            ))
        mentions.append(Mention(
            mention_id=f"{doc.doc_id}#m0", doc_id=doc.doc_id, source_id=doc.source_id,
            surface_form=rd["_subject_surface"],
            resolved_target_id=rd["_subject_id"], resolution_status="resolved",
            source_span=doc.text, event_time=doc.event_time, ingest_time=doc.ingest_time,
            knowledge_time=doc.ingest_time, dup_group_id=doc.dup_group_id,
            is_amplifier=doc.is_amplifier,
        ))
    repo.write_claims(claims)
    repo.write_mentions(mentions)
    print(f"[news] wrote {len(claims)} claims, {len(mentions)} mentions "
          f"(ABOUT edges -> Issuer + MacroIndicator)")

    print(f"[news] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
