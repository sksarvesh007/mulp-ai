"""Request schema for a human review of a claim decision (→ Langfuse dataset)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    """A reviewer's verdict on a processed claim.

    ``criteria`` names the aspects judged wrong (e.g. ``"decision"``,
    ``"approved_amount"``, ``"reasons"``, ``"trace"``); ``expected_notes`` is the
    corrected expected outcome in the reviewer's words. Both are optional when the
    decision is confirmed correct.
    """

    claim_id: str = Field(min_length=1)
    is_correct: bool
    criteria: list[str] = Field(default_factory=list)
    expected_notes: str = ""
