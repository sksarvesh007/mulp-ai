"""Persistence model for processed claims (SQLModel → any SQL backend)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ClaimRecord(SQLModel, table=True):
    __tablename__ = "claims"

    claim_id: str = Field(primary_key=True)
    member_id: str = ""
    category: str = ""
    decision: str | None = None
    status: str = "DECIDED"
    approved_amount: int | None = None
    confidence: float | None = None
    degraded: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    result_json: str = ""  # full ClaimResult, for the detail view
    input_json: str = ""  # original ClaimInput, replayable + needed for review datasets
