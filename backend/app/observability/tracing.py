"""Emit a Langfuse trace per claim, derived from the domain decision-trace.

This makes the pipeline visible in Langfuse's **Tracing** view for *every* claim —
even deterministic eval runs that make no LLM calls — because the trace is
reconstructed from the ``ClaimResult.trace`` events. Enabled only when
``ENABLE_OBSERVABILITY=true`` and Langfuse keys are set; it never raises into the
claim path.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.schemas.decision import ClaimResult


@lru_cache
def get_langfuse() -> Any | None:  # pragma: no cover - requires langfuse + keys
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        return None  # observability group not installed → tracing disabled
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def log_claim_trace(result: ClaimResult) -> None:
    if not get_settings().enable_observability:
        return
    _emit(result)  # pragma: no cover - requires langfuse + a tracking server


def _emit(result: ClaimResult) -> None:  # pragma: no cover
    # observability must NEVER break adjudication — swallow everything, incl. a
    # missing langfuse package or an unreachable server.
    try:
        lf = get_langfuse()
        if lf is None:
            return
        d = result.decision
        headline = str(d.decision) if d.decision else d.status.value
        with lf.start_as_current_observation(
            as_type="span",
            name=f"claim {result.claim_id}",
            input={"claim_id": result.claim_id},
            metadata={
                "decision": headline,
                "approved_amount": d.approved_amount,
                "confidence": d.confidence,
                "degraded": d.degraded,
                "rejection_reasons": d.rejection_reasons,
            },
        ) as root:
            for ev in result.trace:
                with lf.start_as_current_observation(
                    as_type="span",
                    name=ev.step,
                    input=ev.data or None,
                    metadata={"status": str(ev.status), "policy_ref": ev.policy_ref},
                ) as span:
                    span.update(output=ev.detail)
            root.update(output={"decision": headline, "approved_amount": d.approved_amount, "reason": d.reason})
            if d.confidence is not None:
                try:
                    lf.score_current_trace(name="confidence", value=float(d.confidence))
                except Exception:
                    pass
        lf.flush()
    except Exception:
        # observability must never break adjudication
        pass
