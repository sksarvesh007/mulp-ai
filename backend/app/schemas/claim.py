"""Claim submission contracts (the system input)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import ClaimCategory, DocumentQuality, DocumentType, ExtractionMode


class DocumentInput(BaseModel):
    """One uploaded document. In eval mode the harness supplies ``actual_type`` /
    ``quality`` / ``patient_name_on_doc`` / ``content`` hints; in live mode an
    ``image_ref`` (path to the uploaded image/PDF) is supplied instead."""

    file_id: str
    file_name: str | None = None

    # eval-mode hints
    actual_type: DocumentType | None = None
    quality: DocumentQuality | None = None
    patient_name_on_doc: str | None = None
    content: dict[str, Any] | None = None

    # live-mode
    image_ref: str | None = None


class ClaimHistoryItem(BaseModel):
    claim_id: str | None = None
    date: str | None = None
    amount: int | None = None
    provider: str | None = None


class ClaimInput(BaseModel):
    """A claim submission. Mirrors the shape of docs/test_cases.json ``input``."""

    claim_id: str | None = None
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: str  # ISO date (YYYY-MM-DD)
    claimed_amount: int = Field(gt=0)  # a claim for ₹0 or negative is structurally invalid

    hospital_name: str | None = None
    ytd_claims_amount: int = Field(default=0, ge=0)
    submission_date: str | None = None  # if absent, treated as within window (eval)
    pre_auth_reference: str | None = None  # supplied when pre-authorization was obtained
    claims_history: list[ClaimHistoryItem] = Field(default_factory=list)
    documents: list[DocumentInput] = Field(default_factory=list)

    # processing controls
    mode: ExtractionMode = ExtractionMode.EVAL
    simulate_component_failure: bool = False
    # human-in-the-loop: when True, a MANUAL_REVIEW outcome PAUSES the graph at a
    # checkpoint and surfaces a review request instead of finalising automatically.
    hitl: bool = False
