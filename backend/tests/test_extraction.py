from __future__ import annotations

from app.extraction.eval_extractor import EvalExtractor
from app.schemas.claim import DocumentInput
from app.schemas.enums import DocumentQuality, DocumentType

ex = EvalExtractor()


async def test_classify_from_hints() -> None:
    d = DocumentInput(file_id="F", actual_type="PRESCRIPTION", quality="GOOD", patient_name_on_doc="Rajesh Kumar")
    c = await ex.classify(d)
    assert c.doc_type == DocumentType.PRESCRIPTION
    assert c.patient_name == "Rajesh Kumar"


async def test_classify_defaults_unknown() -> None:
    c = await ex.classify(DocumentInput(file_id="F"))
    assert c.doc_type == DocumentType.UNKNOWN
    assert c.quality == DocumentQuality.GOOD


async def test_extract_with_content() -> None:
    d = DocumentInput(
        file_id="F",
        actual_type="HOSPITAL_BILL",
        content={
            "patient_name": "X",
            "total": 1500,
            "test_name": "CBC",
            "medicines": ["Z"],
            "line_items": [{"description": "Y", "amount": 1500}],
            "doctor_registration": "KA/1/2020",
        },
    )
    e = await ex.extract(d)
    assert e.total == 1500
    assert e.line_items[0].amount == 1500
    assert "CBC" in e.tests_ordered
    assert e.ok is True


async def test_extract_no_content_unreadable() -> None:
    d = DocumentInput(file_id="F", actual_type="PHARMACY_BILL", quality="UNREADABLE")
    e = await ex.extract(d)
    assert e.ok is False
    assert e.confidence == 0.0
    assert "UNREADABLE" in e.notes


async def test_extract_no_content_readable() -> None:
    d = DocumentInput(file_id="F", actual_type="PRESCRIPTION", patient_name_on_doc="A")
    e = await ex.extract(d)
    assert e.ok is True
    assert e.patient_name == "A"
    assert "NO_STRUCTURED_CONTENT" in e.notes
