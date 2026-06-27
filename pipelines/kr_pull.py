"""kr_pull.py — load Korean blue-chip issuers (DART) + Korean news into the live graph.

    SKG_STORAGE_BACKEND=neo4j python kr_pull.py        # default top 300 by market cap

Pipeline (mirrors the US path, reuses everything downstream):
  1) DART corpCode -> top-N KRX issuers by market cap (FinanceDataReader bulk join, drops
     개잡주 shells). Cross-lingual: Korean + English names both alias the SAME node.
  2) KSIC industry (company.json) -> :Sector edges so KR issuers cluster (not islands).
  3) yfinance -> :PriceSeries for the KR tickers (.KS/.KQ).
  4) Korean news, two-track: company news (queried by BOTH 한글명 and English name -> one
     node) + 시황/금리/환율 macro news -> existing macro indicator nodes.

KR and US stay DISJOINT components (different legal entities, different markets), joined
only via shared macro indicators — never node-merged. Idempotent (MERGE + URL doc_id).
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg import prefilter
from skg.extract.news_rules import extract_from_headline
from skg.models import Claim, Document, Mention, Source
from skg.sources.dart import DartFetcher
from skg.sources.market import MarketFetcher
from skg.sources.news import NewsFetcher, NaverNewsFetcher, is_quality_outlet
from skg.database import make_repo

TOP_N = int(os.environ.get("SKG_KR_TOP_N", "300"))
NEWS_TOP_N = int(os.environ.get("SKG_KR_NEWS_TOP_N", "300"))


def main() -> None:
    if not cfg.DART_API_KEY:
        print("[kr] no DART key (cfg.DART_API_KEY). Put it in .env and retry.")
        return
    repo = make_repo(cfg)
    repo.init_schema()
    as_of = cfg.AS_OF_NOW
    dart = DartFetcher(cfg.DART_API_KEY)

    # 1) top-N KR issuers by market cap + cross-lingual issuer master
    print(f"[kr] ranking KRX issuers by market cap, taking top {TOP_N}...")
    corps = dart.rank_by_market_cap(TOP_N)
    iss, sec, lst, al = dart.issuer_master(corps)
    repo.write_issuer_master(iss, sec, lst, al)
    print(f"[kr] {len(iss)} KR issuers loaded (KO+EN aliases), e.g. "
          f"{', '.join(c['corp_name'] for c in corps[:5])}")

    # 2) KSIC sectors (one company.json call each — bounded to top-N) -> clusters
    print(f"[kr] fetching KSIC industry for {len(corps)} issuers (sector clusters)...")
    sectors = dart.fetch_sectors(corps)
    repo.write_sectors(sectors)
    print(f"[kr] {len(sectors)} sector edges (issuers cluster by industry)")

    # 3) price series (yfinance, .KS/.KQ from the venue we already know)
    mf = MarketFetcher(window_days=cfg.PRICE_WINDOW_DAYS)
    issuer_tickers = [(f"DART{c['corp_code']}", f"{c['stock_code']}.KR",
                       f"{c['stock_code']}.{c['venue']}") for c in corps]
    print(f"[kr] fetching prices for {len(issuer_tickers)} KR tickers...")
    series = mf.fetch_price_series(issuer_tickers, as_of)
    repo.write_price_series(series)
    print(f"[kr] {len(series)} KR price series")

    # 4) Korean news — two-track. Google News (broad) + Naver (cleaner; originallink = real
    #    publisher so we whitelist by outlet). Same node via Korean name; dedup by doc_id/text.
    fetcher = NewsFetcher()
    naver = None
    if cfg.NAVER_CLIENT_ID and cfg.NAVER_CLIENT_SECRET:
        naver = NaverNewsFetcher(cfg.NAVER_CLIENT_ID, cfg.NAVER_CLIENT_SECRET)
        print("[kr] Naver search enabled (1군 한국 언론만 화이트리스트)")
    news_corps = corps[:NEWS_TOP_N]
    raw_docs: list[dict] = []
    naver_kept = naver_dropped = 0
    for i, c in enumerate(news_corps):
        iid = f"DART{c['corp_code']}"
        # query by Korean name AND English name -> both land on the SAME node (cross-lingual)
        raw_docs.extend(fetcher.fetch_company_news(iid, c["corp_name"], as_of, lang="ko"))
        if c.get("corp_eng_name"):
            raw_docs.extend(fetcher.fetch_company_news(iid, c["corp_eng_name"], as_of, lang="en"))
        if naver:  # Naver KR news, whitelisted to vetted press only
            for d in naver.fetch_company_news(fetcher, iid, c["corp_name"], as_of):
                if is_quality_outlet(d["_outlet"]):
                    raw_docs.append(d); naver_kept += 1
                else:
                    naver_dropped += 1
        if (i + 1) % 50 == 0:
            print(f"[kr] news {i+1}/{len(news_corps)}  docs={len(raw_docs)}")
    if naver:
        print(f"[kr] Naver: kept {naver_kept} (1군 언론), dropped {naver_dropped} (비화이트리스트)")
    macro_docs = fetcher.fetch_macro_news(as_of, lang="ko")
    raw_docs.extend(macro_docs)
    print(f"[kr] fetched {len(raw_docs)} KR articles ({len(macro_docs)} 시황/거시)")

    docs = prefilter.run([Document(d["doc_id"], d["source_id"], d["lang"], d["text"],
                                   d["event_time"], d["ingest_time"]) for d in raw_docs])
    by_id = {d.doc_id: d for d in docs}
    amps = sum(1 for d in docs if d.is_amplifier)
    print(f"[kr] dedup: {amps} amplifier(s) collapsed")

    # register per-outlet sources (KR outlets -> credibility)
    seen = {}
    for rd in raw_docs:
        if rd["source_id"] not in seen:
            seen[rd["source_id"]] = Source(
                rd["source_id"], rd["_outlet"], "major_news" if rd["_cred"] >= 0.5 else "community",
                rd["_cred_class"], rd["_cred"], is_trust_seed=False)
    repo.write_sources(list(seen.values()))

    claims, mentions = [], []
    for rd in raw_docs:
        doc = by_id.get(rd["doc_id"])
        if doc is None:
            continue
        res = extract_from_headline(doc, rd["_subject_surface"])
        for idx, ec in enumerate(res.claims):
            claims.append(Claim(
                claim_id=f"{doc.doc_id}#c{idx}", doc_id=doc.doc_id, source_id=doc.source_id,
                source_credibility=rd["_cred"], subject_id=rd["_subject_id"], relation=ec.relation,
                object_text="", claim_key=ec.claim_key, stance=ec.stance,
                source_span=ec.source_span, span_start=ec.span_start, span_end=ec.span_end,
                event_time=doc.event_time, ingest_time=doc.ingest_time,
                knowledge_time=doc.ingest_time, dup_group_id=doc.dup_group_id,
                is_amplifier=doc.is_amplifier))
        mentions.append(Mention(
            mention_id=f"{doc.doc_id}#m0", doc_id=doc.doc_id, source_id=doc.source_id,
            surface_form=rd["_subject_surface"], resolved_target_id=rd["_subject_id"],
            resolution_status="resolved", source_span=doc.text, event_time=doc.event_time,
            ingest_time=doc.ingest_time, knowledge_time=doc.ingest_time,
            dup_group_id=doc.dup_group_id, is_amplifier=doc.is_amplifier))
    repo.write_claims(claims)
    repo.write_mentions(mentions)
    print(f"[kr] wrote {len(claims)} claims, {len(mentions)} mentions")
    print(f"[kr] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
