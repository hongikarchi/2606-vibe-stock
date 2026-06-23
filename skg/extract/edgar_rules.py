"""RuleBasedEdgarExtractor — the UNATTENDED extractor.

Deterministically maps 8-K item codes (in a Document composed by skg/sources/edgar.py)
to claims against the CLOSED relation enum. Honest capability boundary:

  * risk_flag  — clean. Item code -> bearish/cautious/neutral stance, citing the exact
                 item-description substring as source_span (so grounding can run).
  * sentiment  — neutral stub for results filings (2.02), so the entity gets an endorsement.
  * supplies / competes_with / guides_to / owns — NOT emitted. They require parsing filing
                 prose; a rule engine that fabricated them would defeat the whole point.

So the unattended graph is issuer-dominated with risk_flag/sentiment edges. Richer
relations come from the session-authored path (LayeredExtractor), not from here.
"""
from __future__ import annotations

from ..models import Document
from ..sources.edgar import ITEM_DESCRIPTIONS
from .base import ExtractedClaim, ExtractionResult

# 8-K item code -> (relation, stance). Materiality drives stance; grounding's polarity
# guard then runs over the cited description span.
ITEM_RULES = {
    "1.03": ("risk_flag", "bearish"),   # bankruptcy / receivership
    "2.04": ("risk_flag", "bearish"),   # triggering events accelerating an obligation
    "2.06": ("risk_flag", "bearish"),   # material impairments
    "3.01": ("risk_flag", "bearish"),   # delisting notice
    "4.02": ("risk_flag", "bearish"),   # non-reliance / restatement
    "4.01": ("risk_flag", "cautious"),  # auditor change
    "5.01": ("risk_flag", "cautious"),  # change in control
    "5.02": ("risk_flag", "cautious"),  # departure of directors/officers
    "2.05": ("risk_flag", "cautious"),  # exit/disposal costs
    "2.02": ("sentiment", "neutral"),   # results of operations (endorsement, neutral)
}


class RuleBasedEdgarExtractor:
    def extract(self, doc: Document) -> ExtractionResult:
        # Only EDGAR-composed docs carry the structured fields we key off. The composer
        # stashed them on the dict; ingest.read_corpus drops them, so recover from text.
        items = _items_from_text(doc.text)
        name = _issuer_from_text(doc.text)
        if not name:
            return ExtractionResult(doc_id=doc.doc_id)

        claims = []
        for code in items:
            rule = ITEM_RULES.get(code)
            if rule is None:
                continue
            relation, stance = rule
            desc = ITEM_DESCRIPTIONS.get(code, "")
            span_text = f"{code} {desc}".strip()
            start = doc.text.find(span_text)
            end = start + len(span_text) if start >= 0 else -1
            cik = _cik_from_text(doc.text)
            claims.append(ExtractedClaim(
                subject_surface=name,
                relation=relation,
                object_text="",                 # 8-K items are entity-internal events
                claim_key=f"{cik}:{code}",       # K-of-M grouping per (issuer, item)
                stance=stance,
                source_span=span_text if start >= 0 else "",
                span_start=start,
                span_end=end,
            ))
        return ExtractionResult(
            doc_id=doc.doc_id,
            claims=claims,
            elevated_entities=[name] if claims else [],
        )


class LayeredExtractor:
    """Session-authored extraction takes precedence; the rule engine is the fallback.

    If `<doc_id>.json` exists in session_dir it is used verbatim (via the existing
    FixtureExtractor mechanism) — that's the higher-quality path where the live session
    reads filing prose and writes real supplies/competes_with/guides_to claims. Otherwise
    the deterministic rule extractor runs so the loop keeps making progress unattended.
    """

    def __init__(self, session_dir, fallback):
        from .fixture_extractor import FixtureExtractor
        self.session = FixtureExtractor(session_dir)
        self.fallback = fallback

    def extract(self, doc: Document) -> ExtractionResult:
        from pathlib import Path
        if (Path(self.session.dir) / f"{doc.doc_id}.json").exists():
            return self.session.extract(doc)
        return self.fallback.extract(doc)


# ---- tiny parsers over the composed text (skg/sources/edgar.py::_compose_8k_text) --------
def _items_from_text(text: str) -> list[str]:
    """Pull item codes back out of 'Reported items: 2.02 ...; 9.01 ...' (order preserved)."""
    marker = "Reported items: "
    i = text.find(marker)
    if i < 0:
        return []
    seg = text[i + len(marker):]
    seg = seg.split(". Accession")[0]
    codes = []
    for part in seg.split(";"):
        part = part.strip()
        if part and part[0].isdigit():
            codes.append(part.split()[0])
    return codes


def _issuer_from_text(text: str) -> str:
    """'<Name> (CIK..........) filed a ...' -> '<Name>'."""
    i = text.find(" (CIK")
    return text[:i].strip() if i > 0 else ""


def _cik_from_text(text: str) -> str:
    i = text.find("(CIK")
    if i < 0:
        return ""
    j = text.find(")", i)
    return text[i + 1:j] if j > i else ""
