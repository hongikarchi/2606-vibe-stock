"""SampleReader — ingest synthetic documents from fixtures/corpus/*.json.

Production swap: replace this with real crawlers (DART/EDGAR/GDELT/community). The
contract is the same — emit Document objects with provenance and bi-temporal stamps.
Each corpus file may hold a single doc (object) or a list of docs.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Document


def read_corpus(corpus_dir: str | Path) -> list[Document]:
    corpus_dir = Path(corpus_dir)
    docs: list[Document] = []
    # sorted() for deterministic ingest order regardless of filesystem listing
    for path in sorted(corpus_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
        for rec in records:
            docs.append(
                Document(
                    doc_id=rec["doc_id"],
                    source_id=rec["source_id"],
                    lang=rec.get("lang", "ko"),
                    text=rec["text"],
                    event_time=rec["event_time"],
                    ingest_time=rec.get("ingest_time", rec["event_time"]),
                )
            )
    docs.sort(key=lambda d: d.doc_id)  # stable canonical order
    return docs
