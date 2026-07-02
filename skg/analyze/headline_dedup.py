"""headline_dedup — artifact-level story hygiene: outlet-junk cleaning + near-dup collapse.

Why this exists (2026-07-03 audit of the shipped 이슈연관망): news.py composes claim text as
f"{title}. {summary}", and Google News titles end with " - 매체명" while summaries often
repeat the whole title plus the outlet again — so outlet junk sits MID-string and survived
the old display-time `.split(" - ")`. Worse, one story syndicated by ~8 outlets shipped as
8 near-identical headlines in every drilldown and inflated every count it touched (theme
freq/heat, entity n, edge weight, ThemeDay). Both fixed here, at the ARTIFACT level — Neo4j
is untouched (dedup_news.py remains the exact-dupe store cleaner; per-outlet provenance
stays queryable).

Deterministic. Metric choice is EMPIRICAL, not borrowed: word-token Jaccard (prefilter's
copy-detector) fails on Korean rewrite-syndication — the same story re-headlined by each
outlet ("SKC, AX 전담 조직 출범…" vs "SKC, CEO 직속 AI 전담조직 출범…") scores 0.12-0.38 on
word Jaccard because agglutination splits differently (전담 조직 vs 전담조직). Calibrated on
the live SKC 2026-06-26 bucket (22 claims): char-BIGRAM OVERLAP-coefficient puts true
rewrite pairs at 0.29-1.0 (chaining through >=0.5 intermediates) while genuinely different
items (SkyCity ticker-collision junk, data-page headlines) sit at 0.07-0.20 — so single-link
union-find at >=0.40 inside per-day buckets separates them, plus one adjacent-day merge pass
for the same-story-next-morning case. Representative = (date, text) sort order, first member.

Also home of day_change_from_closes — the ONE shared "today's move" derivation (W1 dashboard,
W2 theme entities, W3 treemap) with a staleness guard so an old close can never ship as a
daily change.
"""
from __future__ import annotations

import datetime
import json
import re
import unicodedata
from collections import defaultdict

import config as cfg

# calibrated on live data (module docstring): true rewrites chain >=0.40, junk stays <=0.20
STORY_BIGRAM_OVERLAP = 0.40

_NONWORD = re.compile(r"[^0-9a-z가-힣]")


def _bigrams(text: str) -> set[str]:
    s = _NONWORD.sub("", unicodedata.normalize("NFKC", text).casefold())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _overlap(a: set[str], b: set[str]) -> float:
    """Overlap coefficient |A∩B|/min(|A|,|B|) — forgiving of the short-title vs
    title+summary length mismatch that deflates plain Jaccard."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _same_story(a: set[str], b: set[str], thr: float) -> bool:
    """Merge predicate: high overlap AND a minimum absolute shared mass — the floor stops
    short-headline coincidences ('코스피 상승 마감' vs '코스닥 상승 마감' share 4 bigrams at
    0.67 overlap: different facts, must NOT merge; true rewrites share 15-60 bigrams)."""
    inter = len(a & b)
    if inter < 8:
        return False
    return inter / min(len(a), len(b)) >= thr


def _known_outlets() -> list[str]:
    # lazy import — keeps analyze/ free of a hard dependency on sources/
    from skg.sources.news import QUALITY_OUTLETS, TIER1_OUTLETS
    return [o.casefold() for o in (list(QUALITY_OUTLETS) + list(TIER1_OUTLETS))]


def _is_known_outlet(tail: str) -> bool:
    t = tail.casefold().strip()
    return any(o in t for o in _known_outlets())


def clean_headline(text: str, outlet: str | None = None, max_len: int = 0) -> str:
    """Strip outlet junk from a composed 'title. summary' string.

    Order matters: (1) exact-outlet removals (the claim row knows its outlet), (2) generic
    ' - 알려진 매체' strip on the title segment, (3) drop a summary prefix that just repeats
    the title. max_len=0 = no truncation (matching/stance run on the full text; display
    call sites pass their own cap).
    """
    t = text or ""
    if outlet:
        # ' - 매체' anywhere (title tail lands mid-string after composition)…
        t = re.sub(re.escape(f" - {outlet}"), "", t, flags=re.IGNORECASE)
        # …and a bare trailing outlet name (summaries often end with it)
        stripped = t.rstrip(" .·|-")
        if stripped.casefold().endswith(outlet.casefold()):
            t = stripped[: len(stripped) - len(outlet)]
    # generic: title segment ending in ' - <credit>' where the credit is a known outlet OR
    # reappears in the body (rows whose outlet field differs from the embedded credit,
    # e.g. '" 씨어스, UAE 계약" - 신한투자증권. 24일 신한투자증권은…')
    seg, sep, rest = t.partition(". ")
    m = re.search(r"\s-\s([^-]{2,40})$", seg)
    if m and (_is_known_outlet(m.group(1))
              or (rest and m.group(1).strip().casefold() in rest.casefold())):
        seg = seg[: m.start()]
    # summary that just repeats the title (news.py only checks the first 30 chars)
    if rest:
        seg_key = seg.casefold().strip()
        rest_key = rest.casefold().strip()
        if seg_key and rest_key.startswith(seg_key):
            rest = rest.strip()[len(seg.strip()):].lstrip(" .·|-")
    t = seg + (". " + rest if rest else "")
    t = " ".join(t.split()).strip(" .·|-— ")
    return t[:max_len].rstrip() if max_len else t


def collapse_groups(records: list[dict], thr: float = STORY_BIGRAM_OVERLAP) -> list[dict]:
    """Collapse rewrite-syndicated stories. records = [{"text", "date", "ent"}] (text already
    cleaned; ent may be None). Returns groups sorted by (date, text):
        {"text": rep_text, "date": rep_date, "ents": sorted distinct ents, "n_src": members}
    One story fetched for two entities keeps BOTH ents (the story genuinely covers both);
    it just stops counting as two stories. Full single-link (union-find) INSIDE each day
    bucket — rep-link alone under-merges because rewrite similarity chains through
    intermediates (A~C~B even when A-B is weak).

    ENTITY-CONSERVATIVE merge rule (calibrated on live failure): US factory-template items
    ("3 Reasons to Avoid ALGN…" vs "…Avoid HSIC…" — ticker-swapped, DIFFERENT stories) are
    textually near-identical, and unrestricted single-link percolated them into 400-item
    blobs. So near-dup merging is allowed only when the two records share the same ent (or
    either has none); EXACT-equal text merges unconditionally (a wire story fetched under
    many company queries is one story). Under-merge residue (same story, two companies,
    slightly different text = counted twice) is accepted: giant blobs destroy attribution,
    double-counting merely inflates modestly and is tracked by quality_report.
    """
    ordered = [r for r in sorted(records, key=lambda r: (r.get("date") or "",
                                                         r.get("text") or ""))
               if r.get("text")]
    by_day: dict[str, list[int]] = defaultdict(list)   # day -> indices into ordered
    grams = [_bigrams(r["text"]) for r in ordered]
    for idx, r in enumerate(ordered):
        by_day[r.get("date") or ""].append(idx)

    parent = list(range(len(ordered)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)   # keep the earliest index as root

    # exact-equal text ON THE SAME DAY = one story regardless of which entity's query
    # fetched it (a wire story lands under hundreds of per-company queries). Same-day only:
    # factory outlets re-publish identical titles for WEEKS — a global exact-text union
    # chained a month of them into one story and gutted the daily trend buckets.
    by_text: dict[tuple[str, str], int] = {}
    for idx, r in enumerate(ordered):
        first = by_text.setdefault((r["text"], r.get("date") or ""), idx)
        if first != idx:
            union(first, idx)

    def _ents_compatible(a: int, b: int) -> bool:
        ea, eb = ordered[a].get("ent"), ordered[b].get("ent")
        return ea == eb or not ea or not eb

    for day, idxs in by_day.items():
        for i, a in enumerate(idxs):
            for b in idxs[i + 1:]:
                if (find(a) != find(b) and _ents_compatible(a, b)
                        and _same_story(grams[a], grams[b], thr)):
                    union(a, b)

    # adjacent-day pass (same story crossing midnight): compare group roots only
    days = sorted(d for d in by_day if d)
    for prev, cur in zip(days, days[1:]):
        try:
            gap = (datetime.date.fromisoformat(cur) - datetime.date.fromisoformat(prev)).days
        except ValueError:
            continue
        if gap != 1:
            continue
        # span guard: only roots whose OWN date is exactly `prev` may absorb `cur` items —
        # otherwise recurring near-identical dailies (market wraps, factory templates)
        # chain across the whole month and flatten the per-day trend
        prev_roots = sorted({find(i) for i in by_day[prev]
                             if (ordered[find(i)].get("date") or "") == prev})
        for j in by_day[cur]:
            rj = find(j)
            if rj != j:
                continue   # not a root — already merged
            for r0 in prev_roots:
                if _ents_compatible(r0, j) and _same_story(grams[r0], grams[j], thr):
                    union(r0, j)
                    break

    groups: dict[int, list[dict]] = defaultdict(list)
    for idx, r in enumerate(ordered):
        groups[find(idx)].append(r)
    out = []
    for root in sorted(groups):
        members = groups[root]
        rep = ordered[root]
        ents = sorted({m.get("ent") for m in members if m.get("ent")})
        out.append({"text": rep["text"], "date": rep.get("date") or "",
                    "ents": ents, "n_src": len(members)})
    return sorted(out, key=lambda g: (g["date"], g["text"]))


def diverse(items: list, max_n: int, text_of=lambda x: x["t"], thr: float = 0.6) -> list:
    """Display-level diversity: greedy keep in given order, skipping items whose bigram
    overlap with an already-kept one is >= thr. COUNTING is untouched — this only stops a
    drilldown list from reading as the same story N times (multi-day re-coverage that the
    day-scoped collapse intentionally keeps as separate stories)."""
    out: list = []
    seen: list[set[str]] = []
    for it in items:
        if len(out) >= max_n:
            break
        g = _bigrams(text_of(it))
        if any(_overlap(g, s) >= thr for s in seen):
            continue
        out.append(it)
        seen.append(g)
    return out


def day_change_from_closes(closes, window_end: str | None, as_of: str,
                           max_age_days: int = 4) -> float | None:
    """Last-bar daily change from a closes window — None unless the window is FRESH.
    A close older than max_age_days must never ship as 'today's move' (label==content)."""
    if isinstance(closes, str):
        try:
            closes = json.loads(closes or "[]")
        except ValueError:
            return None
    if not closes or len(closes) < 2:
        return None
    try:
        age = (datetime.date.fromisoformat(as_of[:10])
               - datetime.date.fromisoformat(str(window_end)[:10])).days
    except (ValueError, TypeError):
        return None
    if age > max_age_days or age < 0:
        return None
    prev, last = closes[-2], closes[-1]
    return round(last / prev - 1.0, 4) if prev else None
