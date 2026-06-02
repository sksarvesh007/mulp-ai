"""Shared helper for building domain trace events."""

from __future__ import annotations

from app.core.clock import now_iso
from app.schemas.enums import TraceStatus
from app.schemas.trace import TraceEvent


def ev(
    step: str,
    status: TraceStatus,
    detail: str,
    policy_ref: str | None = None,
    **data: object,
) -> TraceEvent:
    return TraceEvent(
        step=step,
        status=status,
        detail=detail,
        policy_ref=policy_ref,
        data=dict(data),
        ts=now_iso(),
    )
