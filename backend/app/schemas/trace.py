"""Observability contracts — the domain decision-trace and degradation records.

The ``TraceEvent`` list is the PRIMARY explainability artifact: an ops person must
be able to reconstruct exactly why any claim got any decision from it alone."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import TraceStatus


class TraceEvent(BaseModel):
    step: str  # node / stage name, e.g. "eligibility.waiting_period"
    status: TraceStatus = TraceStatus.INFO
    detail: str  # human-readable, specific
    policy_ref: str | None = None  # JSON path / clause referenced, e.g. "waiting_periods.specific_conditions.diabetes"
    data: dict[str, Any] = Field(default_factory=dict)  # structured payload (numbers, dates)
    ts: str | None = None  # ISO-8601; stamped by the recorder


class ComponentFailure(BaseModel):
    component: str
    error_type: str
    impact: str
    recoverable: bool = True


class ConfidenceDelta(BaseModel):
    reason: str
    delta: float


class ConfidenceBreakdown(BaseModel):
    """Itemized confidence so the score is reproducible — never a magic constant."""

    base: float
    deltas: list[ConfidenceDelta] = Field(default_factory=list)
    final: float
