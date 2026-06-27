"""phrases.py — per-parent PHRASE candidate mining (the CODE half of the issue hierarchy).

The fixed 20-theme gazetteer is coarse-by-design and the emergent miner is unigram-only —
neither can produce a node like "AI 인프라 수요 폭발". This module mines MULTI-WORD candidates
(bi/tri-grams) WITHIN each parent theme's headline bucket, ranked by LIFT × log(count):
specific-to-this-theme phrases rise, theme-generic ones sink.

This is CANDIDATE mining only. Raw output is ~30% gold / ~70% noise (outlet-name fragments,
unrelated company names) — verified empirically. The SESSION (Claude, no API key) curates
these into clean child sub-themes downstream (pipelines/curate_subthemes.py). Code finds
candidates; the LLM picks the meaningful ones — each does what it's good at.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from skg.analyze.emergent import _FUNCTION

_TOK = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")


def _is_kr(w: str) -> bool:
    return any("가" <= c <= "힣" for c in w)


def _toks(text: str) -> list[str]:
    """Ordered topical tokens (function/scaffolding words removed; EN case-folded). Order is
    kept (unlike emergent.tokens which returns a set) because phrases need adjacency."""
    out = []
    for w in _TOK.findall(text or ""):
        wl = w if _is_kr(w) else w.casefold()
        if wl in _FUNCTION:
            continue
        out.append(wl)
    return out


def _ngrams(toks: list[str], nmin: int = 2, nmax: int = 3) -> list[str]:
    out = []
    for n in range(nmin, nmax + 1):
        for i in range(len(toks) - n + 1):
            out.append(" ".join(toks[i:i + n]))
    return out


def mine_candidates(parent_headlines: list[str], all_headlines: list[str],
                    min_count: int = 4, top_k: int = 30) -> list[dict]:
    """Mine phrase candidates for ONE parent theme.

    parent_headlines : headlines tagged with this parent theme (the bucket).
    all_headlines    : the FULL corpus (for the lift denominator — global phrase rate).
    Returns [{phrase, count, lift, score}] top_k by lift × log1p(count).

    lift = (rate of phrase inside this bucket) / (rate across the whole corpus). >1 means the
    phrase is over-represented in this theme — i.e. SPECIFIC to it, not corpus-generic.
    """
    n_all = len(all_headlines) or 1
    n_bucket = len(parent_headlines) or 1

    # global document frequency of each n-gram (distinct headlines containing it)
    global_df: Counter = Counter()
    for h in all_headlines:
        for g in set(_ngrams(_toks(h))):
            global_df[g] += 1

    bucket_df: Counter = Counter()
    for h in parent_headlines:
        for g in set(_ngrams(_toks(h))):
            bucket_df[g] += 1

    cand = []
    for g, c in bucket_df.items():
        if c < min_count or len(g.split()) < 2:
            continue
        bucket_rate = c / n_bucket
        global_rate = (global_df[g] / n_all) or 1e-9
        lift = bucket_rate / global_rate
        cand.append({"phrase": g, "count": c, "lift": round(lift, 2),
                     "score": round(lift * math.log1p(c), 3)})
    cand.sort(key=lambda x: -x["score"])
    return cand[:top_k]
