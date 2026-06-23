"""FixtureExtractor — offline LLMExtractor.

Loads per-document extraction JSON from fixtures/extractions/<doc_id>.json. These files
hold the DELIBERATELY-SKEWED "LLM output" the bias detectors are designed to catch
(dropped whistleblower, bullish-only elevation). If the fixtures were "correct", every
detector would fire nothing and the demo would be blank — the skew IS the point.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Document
from .base import ExtractedClaim, ExtractionResult


class FixtureExtractor:
    def __init__(self, extractions_dir: str | Path):
        self.dir = Path(extractions_dir)

    def extract(self, doc: Document) -> ExtractionResult:
        path = self.dir / f"{doc.doc_id}.json"
        if not path.exists():
            # No skew authored for this doc => empty extraction (the omission baseline
            # will then surface everything the doc actually contained).
            return ExtractionResult(doc_id=doc.doc_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        claims = [
            ExtractedClaim(
                subject_surface=c["subject_surface"],
                relation=c["relation"],
                object_text=c.get("object_text", ""),
                claim_key=c.get("claim_key", ""),
                stance=c.get("stance", "neutral"),
                source_span=c.get("source_span", ""),
                span_start=c.get("span_start", -1),
                span_end=c.get("span_end", -1),
            )
            for c in data.get("claims", [])
        ]
        return ExtractionResult(
            doc_id=doc.doc_id,
            claims=claims,
            elevated_entities=data.get("elevated_entities", []),
        )
