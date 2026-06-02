"""Extraction contracts — produced identically by the eval and live (gpt-5.5 vision)
backends so every downstream node is byte-for-byte agnostic to the perception layer."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import DocumentQuality, DocumentType


class LineItem(BaseModel):
    description: str
    amount: int = Field(ge=0)  # whole rupees, non-negative


class ExtractedField(BaseModel):
    """A single extracted value with provenance + confidence (0..1)."""

    value: object | None = None
    confidence: float = 1.0
    source: str = "eval"  # "eval" | "vision" | "derived"


class ExtractedDocument(BaseModel):
    """Normalized structured fields for one document, plus per-extraction signals."""

    file_id: str
    doc_type: DocumentType = DocumentType.UNKNOWN
    quality: DocumentQuality = DocumentQuality.GOOD

    # Common clinical/billing fields (best-effort; any may be None)
    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    date: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    hospital_name: str | None = None
    medicines: list[str] = Field(default_factory=list)
    tests_ordered: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    total: int | None = None

    # Extraction quality signals
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    low_confidence_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    ok: bool = True  # False if the document could not be extracted at all
    source: str = "eval"
