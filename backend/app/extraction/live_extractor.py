"""Live perception backend.

Two providers, both behind the same ``Extractor`` interface:
  - **gemini** (multimodal): reads document images directly (when a key is set).
  - **deepseek** (text-only): OCRs the image with Tesseract, then structures the text.

When a document already carries structured ``content`` (e.g. an API caller passes
parsed fields), we trust it — so the live backend is usable and testable without a
network round-trip. All network/OCR calls degrade gracefully (return ok=False) and
are guarded by the resilient node wrapper as well.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.extraction.eval_extractor import _coerce
from app.llm.deepseek import deepseek_json
from app.schemas.claim import DocumentInput
from app.schemas.enums import DocumentQuality, DocumentType
from app.schemas.extraction import ExtractedDocument

_CLASSIFY_PROMPT = (
    "You are a medical-document classifier. Classify by the document's FORMAT, not its medical "
    "specialty. Rules: a document with itemized charges and a total amount is a BILL — "
    "HOSPITAL_BILL for a clinic/hospital/dental/eye clinic, PHARMACY_BILL only for a pharmacy/"
    "chemist. A PRESCRIPTION states a diagnosis and medicines (Rx). LAB_REPORT / "
    "DIAGNOSTIC_REPORT / DENTAL_REPORT contain test results or clinical findings WITHOUT charges. "
    'Reply with ONLY a JSON object: {{"doc_type": one of '
    "[PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DIAGNOSTIC_REPORT, DENTAL_REPORT, "
    'DISCHARGE_SUMMARY, UNKNOWN], "patient_name": string|null}}.\n\nDOCUMENT TEXT:\n{text}'
)
_EXTRACT_PROMPT = (
    "Extract structured fields from this Indian medical document text. Reply with ONLY a JSON "
    "object with keys: patient_name, doctor_name, doctor_registration, date, diagnosis, treatment, "
    "hospital_name, medicines (list), tests_ordered (list), line_items (list of "
    "{{description, amount}}), total (number). Use null/empty when unknown. Be faithful; do not "
    "invent amounts.\n\nDOCUMENT TEXT:\n{text}"
)


def _guess_doc_type(file_name: str | None, text: str = "") -> DocumentType:
    """Best-effort document type from filename + OCR-text keywords (classifier fallback)."""
    hay = f"{file_name or ''} {text}".lower()
    if "pharmacy" in hay or "drug lic" in hay:
        return DocumentType.PHARMACY_BILL
    if "prescription" in hay or " rx" in hay or "diagnosis" in hay:
        return DocumentType.PRESCRIPTION
    if "bill" in hay or "invoice" in hay or "receipt" in hay or "total amount" in hay:
        return DocumentType.HOSPITAL_BILL
    if "lab" in hay or "pathology" in hay or "test result" in hay:
        return DocumentType.LAB_REPORT
    if "dental" in hay:
        return DocumentType.DENTAL_REPORT
    return DocumentType.UNKNOWN


class LiveExtractor:
    source = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # OCR is the slow step and ``classify()`` + ``extract()`` both need the same text
        # for a given document. Cache the OCR result per ``image_ref`` so each uploaded
        # document is read exactly once per extractor instance (one pass, not two).
        self._ocr_cache: dict[str, str] = {}

    # ── public interface ─────────────────────────────────────────────────────
    async def classify(self, doc: DocumentInput) -> ExtractedDocument:
        if doc.content is not None or doc.actual_type is not None:
            content = doc.content or {}
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=doc.actual_type or DocumentType.UNKNOWN,
                quality=doc.quality or DocumentQuality.GOOD,
                patient_name=doc.patient_name_on_doc or content.get("patient_name"),
                confidence=0.9,
                source=self.source,
            )
        return await self._llm_classify(doc)  # pragma: no cover - network/OCR path

    async def extract(self, doc: DocumentInput) -> ExtractedDocument:
        if doc.content is not None:
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=doc.actual_type or DocumentType.UNKNOWN,
                quality=doc.quality or DocumentQuality.GOOD,
                confidence=0.9,
                ok=True,
                source=self.source,
                **_coerce(doc.content),
            )
        if doc.image_ref:
            return await self._llm_extract(doc)  # pragma: no cover - network/OCR path
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=doc.actual_type or DocumentType.UNKNOWN,
            quality=doc.quality or DocumentQuality.GOOD,
            ok=False,
            confidence=0.3,
            notes=["NO_CONTENT_OR_IMAGE"],
            source=self.source,
        )

    # ── network / OCR (exercised only in live runs) ──────────────────────────
    def _ocr(self, image_ref: str) -> str:  # pragma: no cover - requires file + tesseract
        from pathlib import Path

        path = Path(image_ref)
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            if len(text.strip()) >= 40:  # real text layer (digital PDF) → use it (fast path)
                return text
            # No/!thin text layer → it's a scanned or image-only PDF. Render each page to an
            # image and OCR it, so images embedded in the PDF are read too.
            return self._ocr_pdf_pages(path) or text

        from PIL import Image

        return self._ocr_image(Image.open(path))

    def _ocr_image(self, original: Any) -> str:  # pragma: no cover - requires tesseract
        """Tesseract on a PIL image, with an enhance/upscale retry for low-yield photos."""
        from PIL import ImageOps

        text = self._tesseract(original)
        if len(text.strip()) >= 40:  # clean document — direct read is best
            return text
        # Low yield (phone photo / low contrast) → grayscale → autocontrast → upscale small images.
        enhanced = ImageOps.autocontrast(original.convert("L"))
        longest = max(enhanced.size)
        if longest < 1600:
            scale = 1600 / longest
            enhanced = enhanced.resize((round(enhanced.width * scale), round(enhanced.height * scale)))
        return self._tesseract(enhanced)

    def _ocr_pdf_pages(self, path: Any) -> str:  # pragma: no cover - requires pdfium + tesseract
        """Rasterize each PDF page (pypdfium2, ~216 DPI) and OCR it — for scanned/image PDFs."""
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            pages = [self._ocr_image(pdf[i].render(scale=3).to_pil()) for i in range(len(pdf))]
        finally:
            pdf.close()
        return "\n".join(pages)

    def _tesseract(self, img: Any) -> str:  # pragma: no cover - requires tesseract
        import io
        import subprocess

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6"],
            input=buf.getvalue(),
            capture_output=True,
            timeout=60,
        )
        return proc.stdout.decode("utf-8", errors="ignore")

    def _safe_ocr(self, image_ref: str | None) -> str:  # pragma: no cover
        if not image_ref:
            return ""
        if image_ref in self._ocr_cache:  # reuse the single OCR pass across classify + extract
            return self._ocr_cache[image_ref]
        try:
            text = self._ocr(image_ref)
        except Exception:
            text = ""
        self._ocr_cache[image_ref] = text
        return text

    async def _llm_classify(self, doc: DocumentInput) -> ExtractedDocument:  # pragma: no cover
        text = self._safe_ocr(doc.image_ref)
        dt = DocumentType.UNKNOWN
        patient = None
        if text.strip():
            try:
                data = await deepseek_json(_CLASSIFY_PROMPT.format(text=text[:6000]), self.settings)
                raw = str(data.get("doc_type", "")).strip().upper().replace(" ", "_").replace("-", "_")
                if raw in DocumentType.__members__:
                    dt = DocumentType(raw)
                patient = data.get("patient_name")
            except Exception:
                pass
        if dt == DocumentType.UNKNOWN:  # filename + OCR-text fallback (never fails)
            dt = _guess_doc_type(doc.file_name, text)
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=dt,
            patient_name=patient,
            quality=DocumentQuality.UNREADABLE if not text.strip() else DocumentQuality.GOOD,
            confidence=0.75,
            source=self.source,
        )

    async def _llm_extract(self, doc: DocumentInput) -> ExtractedDocument:  # pragma: no cover
        text = self._safe_ocr(doc.image_ref)
        # Carry a real document type onto the extracted doc (filename + OCR-text fallback), so
        # downstream consumers — the claim/document consistency check, the advisory agent, the UI —
        # see "hospital bill" / "prescription" rather than UNKNOWN in live runs.
        dt = doc.actual_type or _guess_doc_type(doc.file_name, text)
        if not text.strip():
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=dt,
                quality=DocumentQuality.UNREADABLE,
                ok=False,
                confidence=0.0,
                notes=["UNREADABLE"],
                source=self.source,
            )
        try:
            data = await deepseek_json(_EXTRACT_PROMPT.format(text=text[:8000]), self.settings)
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=dt,
                quality=DocumentQuality.GOOD,
                confidence=0.7,
                ok=True,
                source=self.source,
                **_coerce(data),
            )
        except Exception:
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=dt,
                ok=False,
                confidence=0.0,
                notes=["Automated extraction was unavailable for this document."],
                source=self.source,
            )
