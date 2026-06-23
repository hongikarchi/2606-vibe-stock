"""Bias-defense detectors — the interpretation-integrity layer (research 02b S0–S12).

Four detectors, mapped from the research's S0–S12 onto a 1-2-person-sized surface:
  grounding()              — S0/S1 closed-book span-existence + polarity/hedge guard
  omission()               — S2/S3 recall vs a non-LLM baseline; omitted-mass LOWER bound
  effective_independent()  — S4/S5 origin-vs-amplifier; "K effective of M raw" (UPPER bound)
  stance_dispersion()      — 02c: grounded != unbiased (which grounded facts got elevated)

Key research/attack invariants honored here:
  * omitted-mass is a LOWER bound (correlated captures bias it low) — labeled so.
  * K-effective is an UPPER bound on independence (good-source copying undercounted) — labeled so.
  * grounding proves faithfulness-to-source, not truth.
Determinism: every set-derived output is sorted() before it leaves the function.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from . import lexicon

_WORD = re.compile(r"[0-9A-Za-z가-힣$]+")

# MATERIAL risk-event triggers — the high-materiality signals a knowledge graph must never
# drop (research: "tail-recall@materiality"). Neutral events (공시/수주/guidance) are NOT
# here on purpose: dropping a neutral mention is not a material omission, and flagging it
# floods the human with noise. Omission fires only when a MATERIAL item is dropped.
MATERIAL_TRIGGERS = [
    "감리", "분식", "리콜", "소송", "횡령", "제보", "내부고발", "회계부정",
    "fraud", "lawsuit", "probe", "recall", "embezzle", "whistlebl",
]


# --------------------------------------------------------------------------- 1. grounding
def grounding(claims) -> list[dict]:
    """For each claim: does the cited span resolve to a real substring, and is its polarity
    intact (not a negation/attribution inversion)? Returns one record per FLAGGED claim."""
    flags = []
    for c in claims:
        # span-existence is validated at write time (span_grounded); here we add the
        # cheap polarity guard the attack section requires (substring alone is not enough).
        span = c.source_span or ""
        inverted = lexicon.has_any(span, lexicon.NEGATION)
        attributed = lexicon.has_any(span, lexicon.ATTRIBUTION) or lexicon.has_any(span, lexicon.HEDGE)
        # a claim asserted as a positive/bullish fact whose span is negated or merely attributed
        asserts_fact = c.stance in ("bullish", "bearish") or c.relation != "sentiment"
        if (inverted or attributed) and asserts_fact:
            flags.append({
                "claim_id": c.claim_id,
                "subject": c.subject_id,
                "issue": "polarity-inverted" if inverted else "hedge/attribution-dropped",
                "span": span,
            })
    return sorted(flags, key=lambda d: d["claim_id"])


# --------------------------------------------------------------------------- 2. omission
def _tokens(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _baseline_entities(doc_text: str, gazetteer: set[str],
                       alias_map: dict[str, str]) -> tuple[set[str], set[str]]:
    """Non-LLM baseline over the same text. Returns (entities_C, material_triggers).

    entities_C are CANONICALIZED (삼전 -> 삼성전자) via alias_map so an extractor that used
    a different surface form for the same entity is NOT falsely counted as an omission.
    """
    norm = unicodedata.normalize("NFKC", doc_text)
    raw = {g for g in gazetteer if g and g in norm}
    entities = {alias_map.get(g, g) for g in raw}
    triggers = {t for t in MATERIAL_TRIGGERS if t.casefold() in norm.casefold()}
    return entities, triggers


def omission(docs, extractions, gazetteer: set[str],
             alias_map: dict[str, str] | None = None) -> list[dict]:
    """Per document: recall-at-span of the LLM's elevated set E vs non-LLM baseline C, plus
    an omitted-mass LOWER bound. Fires ONLY when a MATERIAL item (risk event, or an entity
    co-occurring with one) is dropped — neutral-only omissions are noise and suppressed."""
    alias_map = alias_map or {}
    flags = []
    for d in docs:
        ex = extractions.get(d.doc_id)
        if ex is None:
            continue
        C, triggers = _baseline_entities(d.text, gazetteer, alias_map)
        if not C and not triggers:
            continue
        E = {alias_map.get(e, e) for e in ex.elevated_entities}
        full_C = C | triggers
        inter = full_C & E
        recall = len(inter) / len(full_C) if full_C else 1.0
        omissions = sorted(full_C - E)
        # MATERIALITY GATE: only surface if something material was dropped
        dropped_material = (triggers - E)
        if not dropped_material:
            continue
        # capture-recapture (Chapman) lower bound on hidden population
        n1, n2, m = len(E) or 1, len(full_C), max(len(inter), 0)
        n_hat = ((n1 + 1) * (n2 + 1) / (m + 1)) - 1
        union = len(full_C | E)
        hidden = max(n_hat - union, 0.0)
        omitted_lb = hidden / n_hat if n_hat > 0 else 0.0
        flags.append({
            "doc_id": d.doc_id,
            "recall_at_span": round(recall, 3),
            "omissions": omissions,
            "material_dropped": sorted(dropped_material),
            "omitted_mass_lower_bound_pct": round(100 * omitted_lb, 1),
            "label": "최소 추정치 — 두 추출기가 맹점을 공유하면 낮게 편향됨(하한)",
        })
    return sorted(flags, key=lambda d: d["doc_id"])


# --------------------------------------------------------------- 3. effective-independent
def effective_independent(claims) -> list[dict]:
    """Per entity (subject): K effective-independent of M raw, collapsing dup_groups.
    K is an UPPER bound on independence (good-source copying is undetectable)."""
    by_entity: dict[str, list] = {}
    for c in claims:
        by_entity.setdefault(c.subject_id, []).append(c)
    out = []
    for entity, cl in sorted(by_entity.items()):
        m_raw = len(cl)
        groups = {c.dup_group_id or f"solo_{c.claim_id}" for c in cl}
        k_eff = len(groups)
        if m_raw <= 1:
            continue  # nothing to corroborate
        out.append({
            "entity": entity,
            "k_effective": k_eff,
            "m_raw": m_raw,
            "label": f"{k_eff} effective-independent of {m_raw} raw "
                     f"(독립성 상한; good-source 복사는 과소계수)",
        })
    return out


# --------------------------------------------------------------- 4. stance-dispersion
def _stance_hist(texts) -> Counter:
    h = Counter()
    for t in texts:
        h[lexicon.stance_of(t)] += 1
    return h


def _normalized(h: Counter, keys) -> list[float]:
    total = sum(h.values()) or 1
    return [h.get(k, 0) / total for k in keys]


def _jsd(p, q) -> float:
    """Jensen-Shannon divergence, base 2 (bounded [0,1]). Pure-python, deterministic."""
    import math
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]

    def _kl(a, b):
        s = 0.0
        for ai, bi in zip(a, b):
            if ai > 0 and bi > 0:
                s += ai * math.log2(ai / bi)
        return s
    return 0.5 * _kl(p, m) + 0.5 * _kl(q, m)


def stance_dispersion(docs, extractions, threshold: float) -> list[dict]:
    """Per document: compare the stance distribution of ALL sentences vs the ELEVATED ones.
    A skew (e.g. 70% cautionary source -> 80% bullish elevated) is the grounded!=unbiased flag."""
    keys = ("bullish", "bearish", "neutral")
    flags = []
    for d in docs:
        ex = extractions.get(d.doc_id)
        if ex is None or not ex.claims:
            continue
        sentences = [s for s in re.split(r"[.!?。\n]", d.text) if s.strip()]
        if len(sentences) < 2:
            continue
        elevated = [c.source_span or c.object_text for c in ex.claims]
        doc_hist = _stance_hist(sentences)
        elev_hist = _stance_hist(elevated)
        p = _normalized(doc_hist, keys)
        q = _normalized(elev_hist, keys)
        div = _jsd(p, q)
        if div >= threshold:
            flags.append({
                "doc_id": d.doc_id,
                "jsd": round(div, 3),
                "source_stance": dict(doc_hist),
                "elevated_stance": dict(elev_hist),
                "issue": "selection-skew (각 추출은 grounded·참이나 선택이 편향됨)",
            })
    return sorted(flags, key=lambda d: d["doc_id"])


# --------------------------------------------------------------------------- orchestration
def run_all(repo, extractions, docs, as_of, gazetteer=None, alias_map=None) -> dict:
    import config as cfg
    claims = repo.get_claims(as_of)
    gz = gazetteer or set()
    return {
        "grounding": grounding(claims),
        "omission": omission(docs, extractions, gz, alias_map),
        "effective_independent": effective_independent(claims),
        "stance_dispersion": stance_dispersion(docs, extractions, cfg.STANCE_SKEW_JSD),
    }
