from __future__ import annotations

from app.engine.view import build_claim_view
from app.schemas.extraction import ExtractedDocument, LineItem


def test_build_view_merges() -> None:
    docs = [
        ExtractedDocument(file_id="a", diagnosis="Viral Fever", patient_name="Rajesh Kumar", treatment="rest"),
        ExtractedDocument(
            file_id="b",
            hospital_name="Apollo",
            total=1500,
            line_items=[LineItem(description="Consult", amount=1000)],
            tests_ordered=["CBC"],
            patient_name="Rajesh Kumar",
        ),
    ]
    v = build_claim_view(docs)
    assert v.diagnosis_text == "Viral Fever"
    assert v.treatment_text == "rest"
    assert v.hospital_name == "Apollo"
    assert v.bill_total == 1500
    assert v.line_items[0].amount == 1000
    assert "CBC" in v.tests
    assert v.patient_names.count("Rajesh Kumar") == 2
    assert "Viral Fever" in v.condition_text


def test_empty_view() -> None:
    v = build_claim_view([])
    assert v.bill_total is None
    assert v.line_items == []
    assert v.condition_text == ""
