"""loop_build.py — accumulate a real stock knowledge graph in Neo4j, unattended.

Goal (loop engineering): keep fetching real SEC EDGAR issuers + 8-K filings in batches,
MERGE them into Neo4j (idempotent — crash/re-run never duplicates), and periodically run
the full resolve->analyze->export pipeline, until the graph reaches N_NODES_TARGET nodes
or the EDGAR universe is exhausted. Designed to survive hours alone:

  * per-CIK try/except (one bad issuer skips, never aborts the night)
  * retry-with-backoff on HTTP 429/503
  * cursor persisted to EDGAR_STATE after EVERY batch -> a crash resumes, not restarts
  * fetched docs written to REAL_CORPUS as <doc_id>.json with skip-if-exists (dedup)
  * cheap per-batch store (nodes climb); expensive analyze/export only every K batches

Run unattended:
    SKG_STORAGE_BACKEND=neo4j python loop_build.py
The graph is visible live at http://localhost:7474 (login neo4j / skgpassword):
    MATCH (n) RETURN n LIMIT 300

IMPORTANT: run the test suite BEFORE launching this — the conformance test wipes the
graph. Never interleave pytest with a populated loop graph.
"""
from __future__ import annotations

import json
import time
import urllib.error

import config as cfg
import run
from skg import ingest, prefilter
from skg.extract.edgar_rules import LayeredExtractor, RuleBasedEdgarExtractor
from skg.models import Document
from skg.sources.edgar import EdgarFetcher
from skg.database import make_repo

# ---- loop tuning (env-overridable so a full-universe run needs no code edit) ----
import os
ISSUERS_PER_BATCH = int(os.environ.get("SKG_ISSUERS_PER_BATCH", "25"))
FILINGS_PER_ISSUER = int(os.environ.get("SKG_FILINGS_PER_ISSUER", "12"))
# Full re-ingest is O(corpus); at universe scale set this high so the heavy resolve/PPR/
# export runs essentially once at the end. Scaffolding still climbs visibly per batch.
ANALYZE_EVERY = int(os.environ.get("SKG_ANALYZE_EVERY", "8"))
MAX_BATCHES = int(os.environ.get("SKG_MAX_BATCHES", "10000"))


# --------------------------------------------------------------------------- state
def _load_state() -> dict:
    if cfg.EDGAR_STATE.exists():
        return json.loads(cfg.EDGAR_STATE.read_text(encoding="utf-8"))
    return {"offset": 0, "batches": 0}


def _save_state(state: dict) -> None:
    cfg.EDGAR_STATE.parent.mkdir(parents=True, exist_ok=True)
    cfg.EDGAR_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- io helpers
def _write_doc(doc: dict) -> bool:
    """Write one corpus Document JSON; skip if already present (dedup). Returns True if new."""
    cfg.REAL_CORPUS.mkdir(parents=True, exist_ok=True)
    path = cfg.REAL_CORPUS / f"{doc['doc_id']}.json"
    if path.exists():
        return False
    # strip the private _-prefixed carry fields; persist only the Document contract
    payload = {k: v for k, v in doc.items() if not k.startswith("_")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _retry(fn, *a, tries=4, **kw):
    """Call fn with backoff on transient EDGAR errors (429/503/timeouts)."""
    delay = 1.0
    for attempt in range(tries):
        try:
            return fn(*a, **kw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


# --------------------------------------------------------------------------- main loop
def main() -> None:
    repo = make_repo(cfg)
    repo.init_schema()  # non-destructive; safe every run
    fetcher = EdgarFetcher(cfg.EDGAR_USER_AGENT)
    total_issuers = fetcher.universe_size()

    # US issuer universe gate: only ingest S&P500 ∪ NASDAQ-100 issuers (no micro-cap junk
    # polluting the graph). NEWS/MACRO ingestion is unaffected — this gates the EDGAR crawl only.
    from skg.analyze.universe import us_universe_ciks
    try:
        universe = set(us_universe_ciks())
        print(f"[loop] US universe gate: {len(universe)} in-universe CIKs (S&P500 ∪ NASDAQ-100)")
    except Exception as e:  # noqa: BLE001 — if the constituent fetch fails, don't gate (fail open)
        print(f"[loop] WARN universe fetch failed ({type(e).__name__}); ingesting ungated")
        universe = None

    state = _load_state()
    print(f"[loop] start: backend={cfg.STORAGE_BACKEND} target={cfg.N_NODES_TARGET} "
          f"nodes universe={total_issuers} issuers  resuming@offset={state['offset']}")

    new_docs_total = 0
    while True:
        nodes = repo.node_count()
        if nodes >= cfg.N_NODES_TARGET:
            print(f"[loop] target reached: {nodes} >= {cfg.N_NODES_TARGET} nodes")
            break
        if state["offset"] >= total_issuers:
            print(f"[loop] EDGAR universe exhausted at offset {state['offset']}")
            break
        if state["batches"] >= MAX_BATCHES:
            print("[loop] MAX_BATCHES backstop hit")
            break

        offset = state["offset"]
        ciks = fetcher.cik_batch(offset, ISSUERS_PER_BATCH)
        # universe gate: keep only in-universe CIKs (skip the micro-cap crawl entirely)
        if universe is not None:
            ciks = [c for c in ciks if f"CIK{int(c):010d}" in universe]
            if not ciks:
                state["offset"] = offset + ISSUERS_PER_BATCH
                state["batches"] += 1
                _save_state(state)
                continue  # whole slice out-of-universe -> advance without fetching

        # 1) issuer scaffolding for this slice -> MERGE (nodes climb cheaply). Gate to in-universe
        #    issuers so junk never enters the graph. fetch_issuer_universe returns
        #    (issuers, securities, listings, aliases): issuers/securities carry issuer_id,
        #    aliases carry target_id, listings link via security_id -> keep only kept securities'.
        try:
            iss, secu, lst, al = fetcher.fetch_issuer_universe(offset=offset, limit=ISSUERS_PER_BATCH)
            if universe is not None:
                iss = [x for x in iss if x.issuer_id in universe]
                secu = [x for x in secu if x.issuer_id in universe]
                keep_secids = {x.security_id for x in secu}
                lst = [x for x in lst if x.security_id in keep_secids]
                al = [x for x in al if x.target_id in universe]
            repo.write_issuer_master(iss, secu, lst, al)
        except Exception as e:  # noqa: BLE001 — a bad slice must not kill the night
            print(f"[loop] WARN issuer slice @{offset} failed: {type(e).__name__}: {e}")

        # 2) filings per issuer -> corpus files (per-CIK isolation + retry)
        new_docs = 0
        sectors = []
        for cik in ciks:
            try:
                # ONE submissions GET yields filings, formerNames aliases, AND SIC sector
                docs, deep_aliases, sector = _retry(
                    fetcher.fetch_issuer_filings_and_aliases, cik,
                    forms=("8-K",), max_docs=FILINGS_PER_ISSUER)
                if deep_aliases:
                    repo.write_issuer_master([], [], [], deep_aliases)
                if sector:
                    sectors.append(sector)
                for d in docs:
                    if _write_doc(d):
                        new_docs += 1
            except Exception as e:  # noqa: BLE001
                print(f"[loop] WARN CIK{cik} skipped: {type(e).__name__}: {e}")
                continue
        # batch-write the SIC sector edges -> issuer islands become clusters
        repo.write_sectors(sectors)

        new_docs_total += new_docs
        state["offset"] = offset + ISSUERS_PER_BATCH
        state["batches"] += 1
        _save_state(state)  # checkpoint after EVERY batch -> resumable

        nodes = repo.node_count()
        print(f"[loop] batch {state['batches']}: +{len(ciks)} issuers  +{new_docs} docs  "
              f"nodes={nodes}  (corpus_total≈{new_docs_total})")

        # 3) periodic full pipeline: resolve -> store claims -> analyze -> export
        if state["batches"] % ANALYZE_EVERY == 0:
            _run_pipeline(repo)

    # market layer: macro hubs + equity price series (connects issuers to live market data)
    enrich_market(repo)

    # final full pipeline so the graph has claims + AnalysisResult + vault
    _run_pipeline(repo)

    # force-directed visualization (top-N by PageRank, colored by sector) -> out/graph.html
    _write_visual(repo)

    final = repo.node_count()
    print(f"[loop] DONE. nodes={final}  corpus_docs_added≈{new_docs_total}")
    print(f"[loop] graph view -> out/graph.html   |   Neo4j browser -> http://localhost:7474")
    repo.close()


def _write_visual(repo) -> None:
    from pathlib import Path
    from skg.export.force_graph import write_force_graph
    try:
        summary = write_force_graph(repo, cfg.OUT / "graph.html", cfg.AS_OF_NOW, top_n=800)
        print(f"[visual] graph.html: {summary['issuers']} issuers, "
              f"{summary['sectors']} sector clusters, {summary['macro']} macro hubs")
    except Exception as e:  # noqa: BLE001
        print(f"[visual] WARN viz failed (graph intact): {type(e).__name__}: {e}")


def enrich_market(repo) -> None:
    """Add the market layer: macro indicators (FX/rates/commodities/indices) as shared hub
    nodes, and an equity :PriceSeries per issuer (HAS_PRICE edge). Connects the issuer/sector
    structure to live market data. Idempotent (MERGE). Run after issuers/sectors exist."""
    if not cfg.MARKET_ENABLED:
        return
    from skg.sources.market import MarketFetcher
    kt = cfg.AS_OF_NOW  # deterministic knowledge stamp (pipeline avoids wall-clock)
    mf = MarketFetcher(window_days=cfg.PRICE_WINDOW_DAYS)
    print("[market] fetching macro indicators (FX/rates/commodities/indices)...")
    macros = mf.fetch_macro_indicators(kt)
    repo.write_macro(macros)
    print(f"[market] {len(macros)} macro indicators written")

    tickers = repo.get_issuer_tickers()[: cfg.PRICE_MAX_ISSUERS]
    print(f"[market] fetching prices for {len(tickers)} issuers (batched)...")
    series = mf.fetch_price_series(tickers, kt)
    repo.write_price_series(series)
    print(f"[market] {len(series)} price series written  (HAS_PRICE edges)")


def _run_pipeline(repo) -> None:
    """Re-ingest the accumulated real corpus and run the full pipeline ONCE (resolve, store
    claims/mentions, analyze, export). Reuses run.main with the EDGAR issuer master and the
    layered extractor. wipe=False so the Neo4j graph is never destroyed."""
    n_corpus = len(list(cfg.REAL_CORPUS.glob("*.json"))) if cfg.REAL_CORPUS.exists() else 0
    if n_corpus == 0:
        print("[loop] (pipeline skipped — no corpus docs yet)")
        return
    print(f"[loop] --- full pipeline over {n_corpus} accumulated docs ---")
    extractor = LayeredExtractor(cfg.SESSION_EXTRACTIONS, RuleBasedEdgarExtractor())
    try:
        run.main(
            repo=repo,
            corpus_dir=cfg.REAL_CORPUS,
            extractor=extractor,
            issuer_master_path=_edgar_master_path(repo),
            sources_path=cfg.FIXTURES / "sources.json",
            as_of=cfg.AS_OF_NOW,
            wipe=False,
        )
    except Exception as e:  # noqa: BLE001 — analyze must never abort the accumulation
        print(f"[loop] WARN pipeline pass failed (graph intact): {type(e).__name__}: {e}")


def _edgar_master_path(repo):
    """run.main loads issuer master from a JSON path. Snapshot the EDGAR issuers/securities/
    listings/aliases we've MERGE'd into Neo4j to JSON so resolution + display work. Rebuilt
    from the SHARED repo each pipeline pass (cheap, deterministic)."""
    from dataclasses import asdict
    issuers = repo.get_active_universe(cfg.AS_OF_NOW)
    secs = repo._read("MATCH (s:Security) RETURN s {.*} AS s ORDER BY s.security_id")
    lst = repo._read("MATCH (l:Listing) RETURN l {.*} AS l ORDER BY l.listing_id")
    al = repo._read("MATCH (a:Alias) RETURN a {.*} AS a ORDER BY a.alias_key")
    # Alias() takes exactly its dataclass fields; drop the synthetic key and default valid_to
    alias_fields = ("surface_form", "lang", "target_kind", "target_id", "valid_from", "valid_to")
    aliases = []
    for r in al:
        a = r["a"]
        aliases.append({k: a.get(k) for k in alias_fields})
    master = {
        "issuers": [asdict(i) for i in issuers],
        "securities": [r["s"] for r in secs],
        "listings": [r["l"] for r in lst],
        "aliases": aliases,
        "must_not_link": [],
    }
    path = cfg.REAL_CORPUS.parent / "issuer_master.json"
    path.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
