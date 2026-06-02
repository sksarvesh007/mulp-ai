"""Internal result objects produced by each engine stage (consumed by the router)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.decision import DocumentProblem, FinancialBreakdown, FraudSignal, LineItemDecision
from app.schemas.trace import TraceEvent


class GateResult(BaseModel):
    passed: bool
    problem: DocumentProblem | None = None
    trace: list[TraceEvent] = Field(default_factory=list)


class EligibilityResult(BaseModel):
    hard_reject: bool = False
    reasons: list[str] = Field(default_factory=list)
    eligible_from: str | None = None
    headline: str | None = None
    category_covered: bool = True
    member_valid: bool = True
    trace: list[TraceEvent] = Field(default_factory=list)


class FraudResult(BaseModel):
    manual_review: bool = False
    signals: list[FraudSignal] = Field(default_factory=list)
    score: float = 0.0
    trace: list[TraceEvent] = Field(default_factory=list)


class AdjudicationResult(BaseModel):
    skipped: bool = False
    approved_amount: int = 0
    payable: int = 0
    claimed_total: int = 0
    has_excluded: bool = False
    per_claim_exceeded: bool = False
    line_items: list[LineItemDecision] = Field(default_factory=list)
    breakdown: FinancialBreakdown | None = None
    headline: str | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
