"""Merge per-document extractions into a single claim-level view for the rule engine."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.extraction import ExtractedDocument, LineItem


class ClaimView(BaseModel):
    diagnosis_text: str = ""
    treatment_text: str = ""
    condition_text: str = ""  # diagnosis + treatment, for waiting/exclusion matching
    tests: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    bill_total: int | None = None
    hospital_name: str | None = None
    patient_names: list[str] = Field(default_factory=list)


def build_claim_view(extracted: list[ExtractedDocument]) -> ClaimView:
    diagnosis_parts: list[str] = []
    treatment_parts: list[str] = []
    tests: list[str] = []
    line_items: list[LineItem] = []
    totals: list[int] = []
    hospital_name: str | None = None
    patient_names: list[str] = []

    for d in extracted:
        if d.diagnosis:
            diagnosis_parts.append(d.diagnosis)
        if d.treatment:
            treatment_parts.append(d.treatment)
        tests.extend(d.tests_ordered)
        line_items.extend(d.line_items)
        if d.total is not None:
            totals.append(d.total)
        if d.hospital_name and not hospital_name:
            hospital_name = d.hospital_name
        if d.patient_name:
            patient_names.append(d.patient_name)

    diagnosis_text = "; ".join(diagnosis_parts)
    treatment_text = "; ".join(treatment_parts)
    return ClaimView(
        diagnosis_text=diagnosis_text,
        treatment_text=treatment_text,
        condition_text=" ".join([diagnosis_text, treatment_text]).strip(),
        tests=tests,
        line_items=line_items,
        bill_total=max(totals) if totals else None,
        hospital_name=hospital_name,
        patient_names=patient_names,
    )
