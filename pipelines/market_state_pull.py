"""market_state_pull.py — compute & store descriptive market-state indicators.

    SKG_STORAGE_BACKEND=neo4j python market_state_pull.py

(1) 52-week position per issuer -> i.pos_52w  =>  MARKET BREADTH (% near highs vs lows).
(2) Commodity + memory-proxy levels -> :MacroIndicator nodes (구리/은/가스/마이크론/SOXX).

All OBSERVATION (current market state), no lead/lag or prediction. Idempotent.
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
from skg.analyze.market_state import (breadth_summary, fetch_52w_position,
                                      fetch_state_indicators)
from skg.store import make_repo

MAX_ISSUERS = int(os.environ.get("SKG_STATE_MAX", "1200"))


def main() -> None:
    repo = make_repo(cfg)
    as_of = cfg.AS_OF_NOW

    # 1) commodity / memory-proxy state indicators
    print("[state] fetching commodity + memory-proxy prices...")
    inds = fetch_state_indicators(as_of)
    repo.write_macro(inds)
    for m in inds:
        print(f"    {m.name[:22]:22} {m.last_close}  ({m.pct_change_window:+.1%} 3mo)")

    # 2) 52-week position per issuer -> breadth
    syms = repo.get_issuer_symbols()[:MAX_ISSUERS]
    print(f"[state] computing 52w position for {len(syms)} issuers (batched)...")
    positions = fetch_52w_position(syms, as_of)
    repo.set_issuer_52w_position(positions)
    print(f"[state] {len(positions)} issuers stamped with 52w position")

    # market breadth — split US vs KR (different markets, different state)
    us = {k: v for k, v in positions.items() if k.startswith("CIK")}
    kr = {k: v for k, v in positions.items() if k.startswith("DART")}
    print("[state] === MARKET BREADTH (지금 시장 상태) ===")
    for label, pos in [("US (EDGAR)", us), ("KR (DART)", kr), ("전체", positions)]:
        b = breadth_summary(pos)
        if not b:
            continue
        print(f"    [{label:12}] 고점근처(≥80%) {b['pct_near_high']}%  |  "
              f"저점근처(≤20%) {b['pct_near_low']}%  |  중앙값 {b['median_position']}%  (n={b['n']})")

    print(f"[state] DONE. nodes={repo.node_count()}")
    repo.close()


if __name__ == "__main__":
    main()
