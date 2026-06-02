"""Decision contracts — the adjudication output and the member-facing document problem."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    ClaimStatus,
    Decision,
    DocumentProblemType,
    FraudSignalType,
    LineItemStatus,
)
from .trace import ComponentFailure, ConfidenceBreakdown, TraceEvent


class DocumentProblem(BaseModel):
    """Specific, actionable message when the document gate stops a claim early."""

    problem_type: DocumentProblemType
    message: str
    file_ids: list[str] = Field(default_factory=list)
    required_action: str


class LineItemDecision(BaseModel):
    description: str
    amount: int
    status: LineItemStatus
    approved_amount: int = 0
    reason: str | None = None


class FinancialBreakdown(BaseModel):
    """Ordered, human-readable money steps. Network discount is applied BEFORE co-pay."""

    base: int
    is_network: bool = False
    network_discount: int = 0
    after_discount: int = 0
    copay: int = 0
    after_copay: int = 0
    clamps: list[str] = Field(default_factory=list)  # which caps bound, if any
    final: int = 0


class FraudSignal(BaseModel):
    type: FraudSignalType
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """A single tool the agentic reviewer invoked, captured for the trace."""

    name: str
    arguments: str = ""
    output: str = ""


class AIAssessment(BaseModel):
    """Advisory summary from the OpenAI-Agents-SDK reviewer (with policy tools).

    Perception/triage only — it explains the claim in plain language and may raise
    concerns, but it NEVER overrides the deterministic decision.
    """

    summary: str = ""
    concerns: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    tools_used: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ClaimDecision(BaseModel):
    """The complete adjudication result for a claim.

    A document-gate stop is encoded as ``decision=None`` + ``status=NEEDS_MEMBER_ACTION``
    (there is no ``BLOCKED`` value); ``document_problem`` carries the actionable message.
    """

    decision: Decision | None = None
    status: ClaimStatus = ClaimStatus.DECIDED
    approved_amount: int | None = None
    rejection_reasons: list[str] = Field(default_factory=list)

    # itemization / money
    line_items: list[LineItemDecision] = Field(default_factory=list)
    financial_breakdown: FinancialBreakdown | None = None

    # signals
    fraud_signals: list[FraudSignal] = Field(default_factory=list)
    eligible_from: str | None = None  # waiting-period eligibility date

    # confidence + resilience
    confidence: float | None = None
    confidence_breakdown: ConfidenceBreakdown | None = None
    degraded: bool = False
    component_failures: list[ComponentFailure] = Field(default_factory=list)

    # member-facing
    document_problem: DocumentProblem | None = None
    reason: str | None = None  # one-line headline reason
    notes: list[str] = Field(default_factory=list)
    ai_assessment: AIAssessment | None = None  # advisory; from the agentic reviewer if enabled


class HumanReviewRequest(BaseModel):
    """Surfaced to a human when the pipeline pauses a MANUAL_REVIEW claim at a HITL
    checkpoint. Carries everything a reviewer needs to render a verdict."""

    proposed_decision: str  # what the pipeline would have routed to (MANUAL_REVIEW)
    reason: str
    fraud_signals: list[FraudSignal] = Field(default_factory=list)
    claimed_amount: int
    options: list[str] = Field(default_factory=lambda: ["APPROVED", "REJECTED", "PARTIAL"])


class HumanReviewVerdict(BaseModel):
    """A human's verdict, submitted to resume a paused claim from its checkpoint."""

    action: str  # APPROVED | REJECTED | PARTIAL
    approved_amount: int | None = None  # required for APPROVED/PARTIAL; ignored for REJECTED
    reviewer: str = ""
    note: str = ""


class ClaimResult(BaseModel):
    """Top-level response: the decision plus the full reconstructable trace.

    When a claim is paused at a human-in-the-loop checkpoint, ``decision.status`` is
    ``PENDING_REVIEW`` and ``review_request`` carries the reviewer-facing payload.
    """

    claim_id: str
    decision: ClaimDecision
    trace: list[TraceEvent] = Field(default_factory=list)
    review_request: HumanReviewRequest | None = None
