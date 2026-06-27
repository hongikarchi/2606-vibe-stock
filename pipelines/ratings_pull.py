"""ratings_pull.py — analyst ratings (관측, NOT a signal) for top-N issuers.

    SKG_STORAGE_BACKEND=neo4j python pipelines/ratings_pull.py

Fetches institutional analyst data via yfinance: consensus (mean target, # analysts,
rating) + recent per-firm rating CHANGES (Goldman/Morgan Stanley raised/cut, target, date).
Stamps it on Issuer nodes WITH a disclaimer. This is OBSERVATION of what institutions did,
never our recommendation. One Ticker call per issuer → bounded to top-N (default 300).

US: per-firm changes + consensus. KR: consensus only (yfinance gives no KR rating changes).
"""
from __future__ import annotations

import os
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.database import make_repo
from skg.sources.market import MarketFetcher

TOP_N = int(os.environ.get("SKG_RATINGS_TOP_N", "300"))


def main() -> None:
    repo = make_repo(cfg)
    # top-N issuers by PageRank that have a ticker (ratings need a market symbol)
    top = repo._read(
        "MATCH (a:AnalysisResult {as_of:$as_of}) MATCH (i:Issuer {name:a.entity_id}) "
        "RETURN i.issuer_id AS iid ORDER BY a.rank_credible LIMIT $n",
        as_of=cfg.AS_OF_NOW, n=TOP_N)
    want = {r["iid"] for r in top}
    # get_issuer_symbols() -> (issuer_id, yf_symbol); fetch_ratings only needs those two
    syms = [(iid, sym, sym) for iid, sym in repo.get_issuer_symbols() if iid in want]
    print(f"[ratings] fetching analyst ratings for {len(syms)} issuers (관측·추천 아님)...")

    mf = MarketFetcher()
    rows = mf.fetch_ratings(syms, cfg.AS_OF_NOW)
    repo.write_ratings(rows)

    with_changes = sum(1 for r in rows if r["changes"])
    print(f"[ratings] {len(rows)} issuers with analyst coverage; "
          f"{with_changes} have per-firm rating changes (US-heavy)")
    # sample
    for r in rows[:3]:
        c = r["consensus"]
        ch = r["changes"][0] if r["changes"] else None
        nm = repo._read("MATCH (i:Issuer {issuer_id:$iid}) RETURN i.name AS n", iid=r["issuer_id"])
        name = nm[0]["n"] if nm else r["issuer_id"]
        line = f"  {name[:22]}: 목표가평균 {c['target_mean']} (애널 {c['n_analysts']}, {c['rating']})"
        if ch:
            line += f" | 최근: {ch['firm']} {ch['action']} {ch['to']}"
        print(line)
    print(f"[ratings] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
