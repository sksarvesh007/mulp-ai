from __future__ import annotations

from app.extraction.live_extractor import LiveExtractor
from app.schemas.claim import DocumentInput
from app.schemas.enums import DocumentType

ex = LiveExtractor()


async def test_classify_uses_known_type() -> None:
    d = DocumentInput(file_id="F", actual_type="PRESCRIPTION", patient_name_on_doc="Rajesh Kumar")
    c = await ex.classify(d)
    assert c.doc_type == DocumentType.PRESCRIPTION
    assert c.patient_name == "Rajesh Kumar"
    assert c.source == "live"


async def test_extract_with_content() -> None:
    d = DocumentInput(
        file_id="F",
        actual_type="HOSPITAL_BILL",
        content={"total": 1500, "line_items": [{"description": "X", "amount": 1500}]},
    )
    e = await ex.extract(d)
    assert e.ok is True and e.total == 1500 and e.source == "live"


async def test_extract_without_content_or_image_degrades() -> None:
    d = DocumentInput(file_id="F", actual_type="PRESCRIPTION")
    e = await ex.extract(d)
    assert e.ok is False
    assert "NO_CONTENT_OR_IMAGE" in e.notes


def test_safe_ocr_dedupes_per_image_ref(monkeypatch) -> None:
    """classify() + extract() share one OCR pass per document: _safe_ocr OCRs an
    image_ref once, caches it, and serves later calls from the cache."""
    e = LiveExtractor()
    calls = {"n": 0}

    def fake_ocr(image_ref):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return f"ocr-text for {image_ref}"

    monkeypatch.setattr(e, "_ocr", fake_ocr)

    assert e._safe_ocr(None) == ""  # no image_ref → empty, never OCRs
    assert calls["n"] == 0

    first = e._safe_ocr("/tmp/doc.png")  # OCRs once, populates the cache
    assert first == "ocr-text for /tmp/doc.png"
    assert calls["n"] == 1

    second = e._safe_ocr("/tmp/doc.png")  # cache hit — no second OCR pass
    assert second == first
    assert calls["n"] == 1


def test_safe_ocr_caches_failures(monkeypatch) -> None:
    """A failing OCR is caught (returns "") and the empty result is cached, so a flaky
    read isn't retried twice within one claim."""
    e = LiveExtractor()
    calls = {"n": 0}

    def boom(image_ref):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise RuntimeError("ocr unavailable")

    monkeypatch.setattr(e, "_ocr", boom)
    assert e._safe_ocr("/tmp/x.png") == ""
    assert e._safe_ocr("/tmp/x.png") == ""
    assert calls["n"] == 1


def test_observability_noop_when_disabled() -> None:
    from app.core.config import Settings
    from app.observability.setup import setup_observability

    # disabled → must not raise and must not require optional deps
    setup_observability(object(), Settings(enable_observability=False))


def test_langfuse_eval_module_importable() -> None:
    import app.observability.langfuse_eval as m

    assert hasattr(m, "log_eval_run")


def test_guess_doc_type() -> None:
    from app.extraction.live_extractor import _guess_doc_type

    assert _guess_doc_type("dr_sharma_prescription.jpg") == DocumentType.PRESCRIPTION
    assert _guess_doc_type("hospital_bill.png", "BILL RECEIPT Total Amount 1500") == DocumentType.HOSPITAL_BILL
    assert _guess_doc_type("scan.png", "Health First Pharmacy Drug Lic") == DocumentType.PHARMACY_BILL
    assert _guess_doc_type("rep.png", "Pathology test result") == DocumentType.LAB_REPORT
    assert _guess_doc_type("x.png", "Dental crown") == DocumentType.DENTAL_REPORT
    assert _guess_doc_type(None, "") == DocumentType.UNKNOWN


def test_extract_json_handles_fences_and_prose() -> None:
    from app.llm.deepseek import extract_json

    assert extract_json('```json\n{"doc_type": "PRESCRIPTION"}\n```') == {"doc_type": "PRESCRIPTION"}
    assert extract_json('Here is the result: {"total": 1500} cheers') == {"total": 1500}
    assert extract_json(None) == {}
    assert extract_json("no json here") == {}
    assert extract_json("{ not valid }") == {}
    assert extract_json('{"items": [1, 2]}') == {"items": [1, 2]}
    assert extract_json("[1, 2, 3]") == {}  # top-level non-object never coerces
