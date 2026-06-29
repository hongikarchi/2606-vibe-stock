"""loop_metrics.py — quality metrics the autonomous loop compares against baseline.

    python pipelines/loop_metrics.py            # prints JSON metrics of current artifacts

Distinct from verify_artifacts.py: that is the HARD FLOOR (ship/no-ship). This is the SOFT
baseline — the loop keeps a Class-2 change only if it strictly improves a target metric here
with no regression elsewhere. Reads only web/public/data (no DB), so it reflects exactly what
is published. Lower stance_neut_pct is better; lower *_fp_freq is better; the rest are guards.
"""
from __future__ import annotations

import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parents[1] / "web" / "public" / "data"


def _load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def metrics() -> dict:
    themes = _load("themes")
    emergent = _load("emergent")
    graph = _load("graph")
    nodes = {n["id"]: n for n in themes.get("nodes", [])}

    # stance neutrality (lower = better; flagship 개발-vs-거품 signal)
    tb = tr = tn = 0.0
    for n in themes.get("nodes", []):
        s = n.get("stance") or {}
        tb += s.get("bull", 0); tr += s.get("bear", 0); tn += s.get("neut", 0)
    tot = (tb + tr + tn) or 1

    # theme false-positive proxies (lower = better): the audit's polluted sub-nodes
    def freq(tid):  # noqa: ANN001
        return nodes.get(tid, {}).get("freq", 0)

    return {
        "graph_issuers": len(graph.get("issuers", [])),
        "themes_nodes": len(themes.get("nodes", [])),
        "emergent_terms": len(emergent.get("terms", [])),
        "stance_neut_pct": round(tn / tot * 100, 1),
        "stance_bull_pct": round(tb / tot * 100, 1),
        "stance_bear_pct": round(tr / tot * 100, 1),
        "ai_bubble_freq": freq("ai_bubble"),
        "dc_build_freq": freq("dc_build"),
        "datacenter_freq": freq("datacenter"),
        # emergent top hubs (set comparison guards against generic creep / topic loss)
        "emergent_top_hubs": [t["term"] for t in sorted(
            emergent.get("terms", []), key=lambda x: -x.get("deg", 0))[:10]],
    }


if __name__ == "__main__":
    print(json.dumps(metrics(), ensure_ascii=False, indent=2))
