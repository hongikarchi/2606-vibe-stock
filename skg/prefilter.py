"""prefilter — clean text, near-duplicate clustering, origin-vs-amplifier tagging.

This is where a coordinated pump of N near-identical posts gets COLLAPSED to one
dup_group BEFORE analysis, so it cannot inflate importance by sheer volume. The
earliest post in a dup_group (by ingest_time, then doc_id) is the origin (root); the
rest are amplifiers. Deterministic: token-Jaccard over a normalized token set, no
stochastic MinHash.
"""
from __future__ import annotations

import re
import unicodedata

import config as cfg
from .models import Document

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKC", text).casefold()
    return set(_WORD.findall(norm))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def run(docs: list[Document], jaccard_threshold: float | None = None) -> list[Document]:
    """Assign dup_group_id + is_amplifier in place; return the same list."""
    thr = cfg.NEAR_DUP_JACCARD if jaccard_threshold is None else jaccard_threshold
    token_sets = {d.doc_id: _tokens(d.text) for d in docs}

    # Greedy single-link clustering in deterministic doc_id order.
    groups: list[list[Document]] = []
    for d in sorted(docs, key=lambda x: x.doc_id):
        placed = False
        for g in groups:
            # compare to the group representative (first member) — enough for tight pumps
            rep = g[0]
            if _jaccard(token_sets[d.doc_id], token_sets[rep.doc_id]) >= thr:
                g.append(d)
                placed = True
                break
        if not placed:
            groups.append([d])

    for gi, g in enumerate(groups):
        if len(g) == 1:
            g[0].dup_group_id = None
            g[0].is_amplifier = False
            continue
        # origin = earliest ingest_time, then doc_id (you cannot copy from the future)
        ordered = sorted(g, key=lambda x: (x.ingest_time, x.doc_id))
        group_id = f"dup_{ordered[0].doc_id}"
        for idx, d in enumerate(ordered):
            d.dup_group_id = group_id
            d.is_amplifier = idx > 0   # first is the root, rest are amplifiers
    return docs
