"""LLMExtractor — the model swap seam.

Today: FixtureExtractor reads pre-authored (deliberately-skewed) extractions from JSON,
so the pipeline runs fully offline and deterministically. Later: AnthropicExtractor
implements the SAME protocol calling claude-opus-4-8 with strict function-calling against
the fixed relation enum. Nothing else in the pipeline changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Document

# Fixed relation enum — a closed set is what makes KR and EN extractions land on the
# SAME edge type so a bilingual graph collapses (research: open-IE breaks node collapse).
RELATIONS = ["supplies", "competes_with", "owns", "guides_to", "risk_flag", "sentiment"]


@dataclass
class ExtractedClaim:
    subject_surface: str      # surface form (resolved later)
    relation: str
    object_text: str
    claim_key: str            # canonicalized claim object for K-of-M grouping
    stance: str               # bullish | cautious | bearish | neutral
    source_span: str          # cited substring (grounding)
    span_start: int
    span_end: int


@dataclass
class ExtractionResult:
    doc_id: str
    claims: list[ExtractedClaim] = field(default_factory=list)
    # entities the extractor chose to "elevate" (surface forms) — used by omission +
    # stance-dispersion detectors to compare against the non-LLM baseline.
    elevated_entities: list[str] = field(default_factory=list)


class LLMExtractor(Protocol):
    def extract(self, doc: Document) -> ExtractionResult: ...
