"""The Extractor interface. Two backends implement it identically so every
downstream node is agnostic to the perception layer:

  EvalExtractor  — deterministic; trusts the provided content/hints (test harness)
  LiveExtractor  — real multimodal LLM (gpt-5.5 reads the document image directly) for uploads

Contract
--------
classify(doc) -> ExtractedDocument   # doc_type, quality, patient_name populated
extract(doc)  -> ExtractedDocument   # full structured fields + per-field confidence
errors        : never raises for bad content — returns an ExtractedDocument with
                ok=False / low confidence so the pipeline can degrade gracefully.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.claim import DocumentInput
from app.schemas.extraction import ExtractedDocument


class Extractor(Protocol):
    async def classify(self, doc: DocumentInput) -> ExtractedDocument: ...
    async def extract(self, doc: DocumentInput) -> ExtractedDocument: ...
