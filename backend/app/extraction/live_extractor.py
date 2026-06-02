"""Live perception backend.

A single multimodal provider behind the ``Extractor`` interface: the OpenAI base model
(``gpt-5.5``) **reads document images directly** — the uploaded image (or each rendered
PDF page) is sent straight to the model, so there is no OCR step.

One vision call per document does **both** jobs at once: it classifies the document (its
type / relevance) and extracts the key fields. ``classify()`` and ``extract()`` both read
from that single cached call, so an uploaded document is perceived exactly once.

When a document already carries structured ``content`` (e.g. an API caller passes
parsed fields), we trust it — so the live backend is usable and testable without a
network round-trip. All network/image calls degrade gracefully (return ok=False) and
are guarded by the resilient node wrapper as well.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.extraction.eval_extractor import _coerce
from app.llm.openai_client import openai_vision_json
from app.observability.logs import get_logger
from app.schemas.claim import DocumentInput
from app.schemas.enums import DocumentQuality, DocumentType
from app.schemas.extraction import ExtractedDocument

log = get_logger("app.extraction")

# One prompt that does classification (document type / relevance) AND field extraction in a
# single vision call, so we never round-trip the same image twice.
_PERCEIVE_PROMPT = (
    "You are processing an uploaded Indian medical-claim document. Read the attached image and "
    "do BOTH of the following in one pass:\n"
    "(1) CLASSIFY it by FORMAT, not medical specialty: a document with itemized charges and a "
    "total amount is a BILL — HOSPITAL_BILL for a clinic/hospital/dental/eye clinic, PHARMACY_BILL "
    "only for a pharmacy/chemist; a PRESCRIPTION states a diagnosis and medicines (Rx); LAB_REPORT "
    "/ DIAGNOSTIC_REPORT / DENTAL_REPORT contain test results or clinical findings WITHOUT charges. "
    "If the image is not a medical-claim document at all, use UNKNOWN.\n"
    "(2) EXTRACT the key details.\n"
    "Reply with ONLY a JSON object with keys: doc_type (one of [PRESCRIPTION, HOSPITAL_BILL, "
    "LAB_REPORT, PHARMACY_BILL, DIAGNOSTIC_REPORT, DENTAL_REPORT, DISCHARGE_SUMMARY, UNKNOWN]), "
    "patient_name, doctor_name, doctor_registration, date, diagnosis, treatment, hospital_name, "
    "medicines (list), tests_ordered (list), line_items (list of {description, amount}), total "
    "(number). Use null/empty when unknown. Be faithful; do not invent amounts."
)


def _parse_doc_type(value: Any) -> DocumentType | None:
    """Coerce a model-returned doc_type string onto the enum (None if unrecognised)."""
    raw = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    return DocumentType(raw) if raw in DocumentType.__members__ else None


def _guess_doc_type(file_name: str | None, text: str = "") -> DocumentType:
    """Best-effort document type from filename keywords (classifier fallback)."""
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
        # ``classify()`` + ``extract()`` both need the same document image(s). Encoding/
        # rasterizing is the slow local step, so cache the base64 image list per ``image_ref``
        # — each uploaded document is loaded exactly once per extractor instance.
        self._image_cache: dict[str, list[str]] = {}
        # The single combined vision call's result, cached per ``image_ref`` so classify() and
        # extract() share ONE round-trip — each uploaded document is perceived exactly once.
        self._perception_cache: dict[str, tuple[str, dict[str, Any]]] = {}

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

    # ── image loading (exercised only in live runs) ──────────────────────────
    def _load_images(self, image_ref: str) -> list[str]:  # pragma: no cover - requires a file
        """Load a document into base64 data URLs for the vision model. Image files become one
        data URL; PDFs are rasterized one data URL per page (so scanned/image PDFs read too)."""
        from pathlib import Path

        path = Path(image_ref)
        if path.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
            try:
                return [self._encode(pdf[i].render(scale=2).to_pil()) for i in range(len(pdf))]
            finally:
                pdf.close()

        from PIL import Image

        return [self._encode(Image.open(path))]

    def _encode(self, img: Any) -> str:  # pragma: no cover - requires PIL
        """A PIL image → a base64 JPEG data URL, downscaled so the upload payload stays sane."""
        import base64
        import io

        img = img.convert("RGB")
        longest = max(img.size)
        if longest > 2000:  # cap the longest side — keeps the request small without losing legibility
            scale = 2000 / longest
            img = img.resize((round(img.width * scale), round(img.height * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    def _safe_images(self, image_ref: str | None) -> list[str]:  # pragma: no cover
        if not image_ref:
            return []
        if image_ref in self._image_cache:  # reuse the single load across classify + extract
            return self._image_cache[image_ref]
        try:
            images = self._load_images(image_ref)
        except Exception:
            images = []
        self._image_cache[image_ref] = images
        return images

    async def _perceive(self, doc: DocumentInput) -> tuple[str, dict[str, Any]]:  # pragma: no cover
        """One combined vision call (classify + extract), cached per ``image_ref`` so classify()
        and extract() share it. Returns ``(status, data)`` where status is:
          - ``"unreadable"`` — no image could be loaded (nothing to send the model)
          - ``"error"``      — image(s) sent but the model call failed
          - ``"ok"``         — ``data`` holds the parsed doc_type + extracted fields
        """
        ref = doc.image_ref
        if ref and ref in self._perception_cache:  # the single round-trip, reused
            log.debug("perceive.cache_hit", file_id=doc.file_id)
            return self._perception_cache[ref]
        images = self._safe_images(ref)
        if not images:
            out: tuple[str, dict[str, Any]] = ("unreadable", {})
        else:
            try:
                out = ("ok", await openai_vision_json(_PERCEIVE_PROMPT, images, self.settings))
            except Exception:
                out = ("error", {})
        log.info(
            "perceive",
            file_id=doc.file_id,
            file_name=doc.file_name,
            images=len(images),
            status=out[0],
            doc_type=out[1].get("doc_type"),
        )
        if ref:
            self._perception_cache[ref] = out
        return out

    async def _llm_classify(self, doc: DocumentInput) -> ExtractedDocument:  # pragma: no cover
        status, data = await self._perceive(doc)
        # vision-read type, else a filename fallback (never fails)
        dt = _parse_doc_type(data.get("doc_type")) or _guess_doc_type(doc.file_name)
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=dt,
            patient_name=data.get("patient_name"),
            quality=DocumentQuality.UNREADABLE if status == "unreadable" else DocumentQuality.GOOD,
            confidence=0.75,
            source=self.source,
        )

    async def _llm_extract(self, doc: DocumentInput) -> ExtractedDocument:  # pragma: no cover
        status, data = await self._perceive(doc)
        # Carry a real document type onto the extracted doc so downstream consumers — the
        # claim/document consistency check, the advisory agent, the UI — see "hospital bill" /
        # "prescription" rather than UNKNOWN in live runs. The vision model reads the type off
        # the image itself; the filename is only the last-resort fallback.
        dt = doc.actual_type or _parse_doc_type(data.get("doc_type")) or _guess_doc_type(doc.file_name)
        if status == "unreadable":
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=dt,
                quality=DocumentQuality.UNREADABLE,
                ok=False,
                confidence=0.0,
                notes=["UNREADABLE"],
                source=self.source,
            )
        if status == "error":
            return ExtractedDocument(
                file_id=doc.file_id,
                doc_type=dt,
                ok=False,
                confidence=0.0,
                notes=["Automated extraction was unavailable for this document."],
                source=self.source,
            )
        return ExtractedDocument(
            file_id=doc.file_id,
            doc_type=dt,
            quality=DocumentQuality.GOOD,
            confidence=0.7,
            ok=True,
            source=self.source,
            **_coerce(data),
        )
