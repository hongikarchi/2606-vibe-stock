"""Gate freshness semantics (verify_artifacts §7) — pinned by test so the N-of-M design
survives future edits: 1-2 stale macros = upstream feed lag (tolerated; ^TNX was verified
4 sessions behind at Yahoo itself), >=3 stale = refresh-mechanism failure (blocked).
Synthetic artifacts only — no DB, no network, no dependence on live data values."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipelines"))

import verify_artifacts as va  # noqa: E402

AS_OF = "2026-07-02T00:00:00"


def _artifacts(macro_ends=None, price_fresh=99.9, drop_price_key=False):
    """Minimal artifact set that passes every non-freshness invariant."""
    macros = [{"name": f"m{i}", "end": e} for i, e in enumerate(macro_ends or [])]
    meta = {"as_of": AS_OF, "price_fresh_pct": price_fresh}
    if drop_price_key:
        meta.pop("price_fresh_pct")
    return {
        "meta": meta,
        "themes": {"nodes": [{"id": t, "heads": []} for t in
                             ["semiconductor", "ai", "datacenter", "ev_battery"]
                             + [f"t{i}" for i in range(60)]]},
        "emergent": {"terms": [{"term": f"w{i}", "deg": 1} for i in range(120)]},
        "graph": {"issuers": [{"name": "SK하이닉스", "heads": []}]
                  + [{"name": f"co{i}", "heads": []} for i in range(400)]},
        "dashboard": {"as_of": AS_OF, "us": [1], "kr": [1], "hot": [1], "cold": [1],
                      "macros": macros},
    }


def _fresh_fails(arts):
    orig = va._load
    va._load = lambda name: arts[name]
    try:
        return [f for f in va.check() if f.startswith("[fresh]")]
    finally:
        va._load = orig


FRESH = ["2026-07-01"] * 12
def _stale(n):
    return ["2026-06-01"] * n + FRESH[n:]


def test_all_fresh_passes():
    assert _fresh_fails(_artifacts(FRESH)) == []


def test_single_feed_lag_tolerated():
    assert _fresh_fails(_artifacts(_stale(1))) == []
    assert _fresh_fails(_artifacts(_stale(2))) == []


def test_mechanism_failure_blocks():
    assert _fresh_fails(_artifacts(_stale(3)))
    assert _fresh_fails(_artifacts(_stale(12)))  # the original all-frozen defect


def test_empty_macro_list_blocks():
    assert any("empty" in f for f in _fresh_fails(_artifacts([])))


def test_dateless_macros_block():
    arts = _artifacts(FRESH)
    for m in arts["dashboard"]["macros"]:
        m.pop("end")
    assert any("window-end" in f for f in _fresh_fails(arts))


def test_price_fresh_floor():
    assert any("price_fresh_pct=12.0" in f
               for f in _fresh_fails(_artifacts(FRESH, price_fresh=12.0)))
    assert any("missing" in f
               for f in _fresh_fails(_artifacts(FRESH, drop_price_key=True)))


def test_malformed_end_is_not_a_crash():
    arts = _artifacts(FRESH)
    arts["dashboard"]["macros"][0]["end"] = "garbage"
    assert _fresh_fails(arts) == []  # counted as dateless, not a traceback
