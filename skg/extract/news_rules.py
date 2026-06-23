"""NewsRuleExtractor — unattended headline extractor.

The subject is KNOWN (we queried by entity), so no entity extraction is needed — the hard
part is sidestepped. From the headline we emit, against the closed relation enum:

  * sentiment  — always, stance from the bilingual lexicon (the headline's tone toward the subject)
  * risk_flag  — when a MATERIAL_TRIGGER word appears (소송/리콜/fraud/lawsuit/probe...), stance bearish

source_span is the real headline with correct offsets, so the grounding polarity guard
fires exactly as designed: "bankruptcy fears DENIED" (negated) is caught, not stored bearish.
Richer inter-company relations (A supplies B) stay the session-authored overlay; this
rule path keeps the unattended loop moving.
"""
from __future__ import annotations

from ..analyze import lexicon
from ..analyze.detectors import MATERIAL_TRIGGERS
from ..models import Document
from .base import ExtractedClaim, ExtractionResult


def extract_from_headline(doc: Document, subject_surface: str) -> ExtractionResult:
    """Build claims for a news Document whose subject surface form is known."""
    text = doc.text
    stance = lexicon.stance_of(text)
    claims = [ExtractedClaim(
        subject_surface=subject_surface, relation="sentiment", object_text="",
        claim_key=f"news_sentiment:{subject_surface}", stance=stance,
        source_span=text, span_start=0, span_end=len(text),
    )]
    # material risk event mentioned in the headline -> a risk_flag claim (bearish)
    low = text.casefold()
    hit = next((t for t in MATERIAL_TRIGGERS if t.casefold() in low), None)
    if hit:
        idx = low.find(hit.casefold())
        claims.append(ExtractedClaim(
            subject_surface=subject_surface, relation="risk_flag", object_text="",
            claim_key=f"news_risk:{subject_surface}:{hit}", stance="bearish",
            source_span=text, span_start=idx, span_end=idx + len(hit),
        ))
    return ExtractionResult(doc_id=doc.doc_id, claims=claims,
                            elevated_entities=[subject_surface])
