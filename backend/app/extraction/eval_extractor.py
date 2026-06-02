"""Deterministic eval-mode extractor — trusts the provided ``content``/hints.
No LLM, so the 12-case eval is fully reproducible and exercises the *real* decision
logic (only perception is swapped out)."""

from __future__ import annotations

from typing import Any

from app.schemas.claim import DocumentInput
from app.schemas.enums import DocumentQuality, DocumentType
from app.schemas.extraction import ExtractedDocument, LineItem


def _coerce(content: dict[str, Any]) -> dict[str, Any]:
    """Map a test-case ``content`` blob onto ExtractedDocument fields."""
    line_items = [
        LineItem(description=str(li.get("description", "")), amount=int(li.get("amount", 0)))
        for li in content.get("line_items", [])
        if isinstance(li, dict)
    ]
    tests = list(content.get("tests_ordered", []))
    if content.get("test_name"):
        tests.append(str(content["test_name"]))
    return {
        "patient_name": content.get("patient_name"),
        "doctor_name": content.get("doctor_name"),
        "doctor_registration": content.get("doctor_registration"),
        "date": content.get("date"),
        "diagnosis": content.get("diagnosis"),
        "treatment": content.get("treatment"),
        "hospital_name": content.get("hospital_name"),
        "medicines": list(content.get("medicines", [])),
        "tests_ordered": tests,
        "line_items": line_items,
        "total": int(content["total"]) if content.get("total") is not None else None,
    }


class EvalExtractor:
    """Test-harness backend."""

    source = "eval"

    async def classify(self, doc: DocumentInput) -> ExtractedDocument:
        content = doc.content or {}
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=doc.actual_type or DocumentType.UNKNOWN,
            quality=doc.quality or DocumentQuality.GOOD,
            patient_name=doc.patient_name_on_doc or content.get("patient_name"),
            confidence=1.0,
            source=self.source,
        )

    async def extract(self, doc: DocumentInput) -> ExtractedDocument:
        quality = doc.quality or DocumentQuality.GOOD
        if doc.content is None:
            # TC001-003: only type/quality/patient hints, no structured content
            unreadable = quality == DocumentQuality.UNREADABLE
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=doc.actual_type or DocumentType.UNKNOWN,
                quality=quality,
                patient_name=doc.patient_name_on_doc,
                confidence=0.0 if unreadable else 0.6,
                ok=not unreadable,
                notes=["UNREADABLE"] if unreadable else ["NO_STRUCTURED_CONTENT"],
                source=self.source,
            )
        fields = _coerce(doc.content)
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=doc.actual_type or DocumentType.UNKNOWN,
            quality=quality,
            confidence=0.97,
            ok=True,
            source=self.source,
            **fields,
        )
