"""Render document images for the 12 cases so the LIVE LLM path can be evaluated.

Each case's documents are drawn as clear, OCR-friendly images. The generated
DocumentInputs carry NO ``actual_type`` and NO ``content`` — only an ``image_ref`` —
so the live pipeline must classify and extract them with the LLM (gpt-5.5 vision).
The ``quality: UNREADABLE`` hint is rendered as a heavily-degraded image so OCR fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.schemas.claim import DocumentInput

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "eval_docs"

_HEADERS = {
    "PRESCRIPTION": "MEDICAL PRESCRIPTION (Rx)",
    "HOSPITAL_BILL": "HOSPITAL BILL / RECEIPT",
    "PHARMACY_BILL": "PHARMACY BILL",
    "LAB_REPORT": "DIAGNOSTIC LAB REPORT",
    "DIAGNOSTIC_REPORT": "DIAGNOSTIC REPORT",
    "DENTAL_REPORT": "DENTAL REPORT",
}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _lines_for(doc_type: str, content: dict[str, Any] | None, patient_hint: str | None) -> list[str]:
    lines = [_HEADERS.get(doc_type, "MEDICAL DOCUMENT"), ""]
    c = content or {}
    patient = patient_hint or c.get("patient_name")
    if c.get("hospital_name"):
        lines.append(f"Facility: {c['hospital_name']}")
    if c.get("doctor_name"):
        reg = f"   Reg. No: {c['doctor_registration']}" if c.get("doctor_registration") else ""
        lines.append(f"Doctor: {c['doctor_name']}{reg}")
    if patient:
        lines.append(f"Patient: {patient}")
    if c.get("date"):
        lines.append(f"Date: {c['date']}")
    if c.get("diagnosis"):
        lines.append(f"Diagnosis: {c['diagnosis']}")
    if c.get("treatment"):
        lines.append(f"Treatment: {c['treatment']}")
    if c.get("medicines"):
        lines.append("Rx: " + ", ".join(str(m) for m in c["medicines"]))
    tests = list(c.get("tests_ordered", []))
    if c.get("test_name"):
        tests.append(str(c["test_name"]))
    if tests:
        lines.append("Investigations: " + ", ".join(tests))
    for li in c.get("line_items", []):
        lines.append(f"{li.get('description', ''):<34} Rs {li.get('amount', 0)}")
    if c.get("total") is not None:
        lines.append(f"Total Amount: Rs {c['total']}")
    if not content and doc_type == "PRESCRIPTION":
        lines += ["Diagnosis: General consultation", "Rx: as advised"]
    if not content and doc_type in ("HOSPITAL_BILL", "PHARMACY_BILL"):
        lines += ["Total Amount: Rs 0"]
    return lines


def _render(lines: list[str], path: Path, unreadable: bool = False) -> None:
    width = 1000
    height = 90 + len(lines) * 46
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 40
    for i, text in enumerate(lines):
        draw.text((40, y), text, fill="black", font=_font(30 if i == 0 else 26))
        y += 46
    if unreadable:
        # destroy legibility so OCR returns nothing → gate flags UNREADABLE
        small = img.resize((width // 6, height // 6)).resize((width, height))
        img = small.filter(ImageFilter.GaussianBlur(7))
    img.save(path)


def generate_documents(case: dict[str, Any]) -> list[DocumentInput]:
    case_id = case["case_id"]
    out = OUT_DIR / case_id
    out.mkdir(parents=True, exist_ok=True)
    docs: list[DocumentInput] = []
    for i, doc in enumerate(case["input"]["documents"]):
        doc_type = doc.get("actual_type", "DOCUMENT")
        quality = doc.get("quality", "GOOD")
        lines = _lines_for(doc_type, doc.get("content"), doc.get("patient_name_on_doc"))
        # filename carries the type hint (used only as a classifier fallback)
        fname = f"{doc_type.lower()}_{i + 1}.png"
        path = out / fname
        _render(lines, path, unreadable=(quality == "UNREADABLE"))
        docs.append(DocumentInput(file_id=doc.get("file_id", f"F{i}"), file_name=fname, image_ref=str(path)))
    return docs
