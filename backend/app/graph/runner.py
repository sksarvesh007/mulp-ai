"""Run a claim through the compiled graph and assemble the final ClaimResult."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command

from app.core.config import get_settings
from app.db.ledger import load_member_history, record_claim
from app.engine.trace_util import ev
from app.graph.build import get_graph, get_hitl_graph
from app.observability.tracing import log_claim_trace
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimDecision, ClaimResult, HumanReviewRequest, HumanReviewVerdict
from app.schemas.enums import ClaimStatus, TraceStatus
from app.schemas.trace import TraceEvent


def _claim_id(claim: ClaimInput, claim_id: str | None) -> str:
    return claim_id or claim.claim_id or f"CLM_{uuid.uuid4().hex[:10]}"


def _assemble(cid: str, final: dict[str, Any]) -> ClaimResult:
    """Build a finished ClaimResult from a completed graph run's final state."""
    decision = final.get("decision") or ClaimDecision(
        decision=None, status=ClaimStatus.DECIDED, reason="No decision produced."
    )
    # surface degradation captured outside the router (e.g. on the gate path)
    failures = final.get("failures", [])
    if failures and not decision.component_failures:
        decision.component_failures = failures
        decision.degraded = bool(final.get("degraded", False))

    trace = sorted(final.get("trace_events", []), key=lambda e: e.ts or "")
    result = ClaimResult(claim_id=cid, decision=decision, trace=trace)
    log_claim_trace(result)
    return result


async def run_claim(claim: ClaimInput, *, claim_id: str | None = None) -> ClaimResult:
    cid = _claim_id(claim, claim_id)
    await load_member_history(claim)  # LIVE-only: pull the member's prior claims for fraud velocity
    final = await get_graph().ainvoke({"claim": claim})
    result = _assemble(cid, final)
    await record_claim(claim, result)  # LIVE-only: persist this submission to the ledger
    return result


async def run_claim_hitl(claim: ClaimInput, *, claim_id: str | None = None) -> ClaimResult:
    """Run a claim through the checkpointed HITL graph. If it routes to MANUAL_REVIEW the
    graph PAUSES at the ``human_review`` node (state saved by the checkpointer) and this
    returns a PENDING_REVIEW result carrying the reviewer-facing ``review_request``; the
    ``claim_id`` is the checkpoint thread_id used to resume. Otherwise it returns the final
    decision exactly like ``run_claim``."""
    cid = _claim_id(claim, claim_id)
    config = {"configurable": {"thread_id": cid}}
    final = await get_hitl_graph().ainvoke({"claim": claim}, config=config)

    interrupts = final.get("__interrupt__")
    if interrupts:  # paused at the HITL checkpoint
        request = HumanReviewRequest.model_validate(interrupts[0].value)
        decision = ClaimDecision(
            decision=None,
            status=ClaimStatus.PENDING_REVIEW,
            reason=request.reason,
            fraud_signals=request.fraud_signals,
        )
        trace = sorted(final.get("trace_events", []), key=lambda e: e.ts or "")
        result = ClaimResult(claim_id=cid, decision=decision, trace=trace, review_request=request)
        log_claim_trace(result)
        return result

    return _assemble(cid, final)  # non-MANUAL_REVIEW HITL claims fall through unchanged


async def resume_claim(*, claim_id: str, verdict: HumanReviewVerdict) -> ClaimResult:
    """Resume a paused claim from its checkpoint with a human's verdict. The checkpoint
    already holds the full state (incl. the claim), so only the thread_id + verdict are
    needed; the graph re-enters ``human_review``, applies the verdict, and finalises."""
    config = {"configurable": {"thread_id": claim_id}}
    final = await get_hitl_graph().ainvoke(Command(resume=verdict.model_dump()), config=config)
    return _assemble(claim_id, final)


async def stream_claim(claim: ClaimInput, *, claim_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Stream pipeline progress events, then a final ``result`` event carrying the
    full ClaimResult. Used by the SSE endpoint to drive the live UI."""
    cid = _claim_id(claim, claim_id)
    decision: ClaimDecision | None = None
    trace: list[Any] = []
    failures: list[Any] = []
    degraded = False
    view: Any = None
    extracted_docs: list[Any] = []
    interrupt_value: Any = None

    await load_member_history(claim)  # LIVE-only: prior submissions feed the fraud velocity check
    # A HITL claim (e.g. an upload that may need human review) streams through the CHECKPOINTED
    # graph so a MANUAL_REVIEW outcome PAUSES at human_review instead of finalising; everything
    # else streams through the plain graph unchanged.
    graph = get_hitl_graph() if claim.hitl else get_graph()
    config = {"configurable": {"thread_id": cid}} if claim.hitl else None
    async for mode, chunk in graph.astream({"claim": claim}, config=config, stream_mode=["custom", "updates"]):
        if mode == "custom":
            yield {"type": "progress", **chunk}
            continue
        for node, delta in chunk.items():
            # The graph paused at the HITL checkpoint — capture the review request and stop;
            # the decision isn't finalised, it's awaiting a human.
            if node == "__interrupt__":
                interrupt_value = delta
                continue
            # A node that returns an empty delta (e.g. human_review passthrough) streams a
            # None update — still a visible step, just with nothing to merge.
            delta = delta or {}
            if delta.get("decision") is not None:
                decision = delta["decision"]
            if delta.get("view") is not None:
                view = delta["view"]
            extracted_docs.extend(delta.get("extracted_docs") or [])
            trace.extend(delta.get("trace_events") or [])
            failures.extend(delta.get("failures") or [])
            degraded = degraded or bool(delta.get("degraded"))
            yield {"type": "node", "node": node}

    # HITL pause: the claim routed to MANUAL_REVIEW and the graph interrupted at human_review.
    # Surface a PENDING_REVIEW result carrying the reviewer-facing request; the checkpoint (keyed
    # by this claim_id) lets POST /claims/{id}/resume continue from here with a human's verdict.
    if interrupt_value is not None:
        request = HumanReviewRequest.model_validate(interrupt_value[0].value)
        pending = ClaimDecision(
            decision=None,
            status=ClaimStatus.PENDING_REVIEW,
            reason=request.reason,
            fraud_signals=request.fraud_signals,
        )
        trace.sort(key=lambda e: e.ts or "")
        result = ClaimResult(claim_id=cid, decision=pending, trace=trace, review_request=request)
        await record_claim(claim, result)  # the submission is logged even while it awaits review
        yield {"type": "pending_review", "result": result}
        log_claim_trace(result)
        return

    if decision is None:  # pragma: no cover - defensive; a node always sets a decision
        decision = ClaimDecision(decision=None, status=ClaimStatus.DECIDED, reason="No decision produced.")
    if failures and not decision.component_failures:
        decision.component_failures = failures
        decision.degraded = degraded
    trace.sort(key=lambda e: e.ts or "")
    result = ClaimResult(claim_id=cid, decision=decision, trace=trace)
    await record_claim(claim, result)  # LIVE-only: persist this submission to the ledger
    yield {"type": "result", "result": result}

    # The advisory AI agent runs OFF the critical path: the decision has already streamed,
    # so its assessment arrives LATER as a separate event without blocking the decision.
    # It runs for EVERY streamed claim — demo (eval) and upload (live) alike — so both drive
    # the identical pipeline, including the agentic node. When it runs, fold its tool calls
    # into the trace so it ALSO shows up in Langfuse — which is why the Langfuse trace is
    # emitted HERE (after the agent), not before.
    assessment = await _maybe_run_agentic_review(claim, view, extracted_docs, result.decision)
    if assessment is not None:
        result.decision.ai_assessment = assessment
        result.trace.extend(_agent_trace_events(assessment))
        yield {"type": "ai_assessment", "assessment": assessment.model_dump(mode="json")}
    log_claim_trace(result)


def _agent_trace_events(assessment: Any) -> list[TraceEvent]:
    """Turn the advisory agent's tool calls + summary into trace events, so the agent is
    visible both in the domain trace and as spans in the reconstructed Langfuse trace."""
    tools = ", ".join(assessment.tools_used) or "none"
    events = [
        ev(
            f"agent.{tc.name}",
            TraceStatus.INFO,
            f"Tool {tc.name}({tc.arguments}) → {tc.output[:160]}",
            tool=tc.name,
            arguments=tc.arguments,
            output=tc.output[:500],
        )
        for tc in assessment.tool_calls
    ]
    events.append(
        ev("agentic_review", TraceStatus.INFO, f"AI reviewer (tools used: {tools}): {assessment.summary}")
    )
    return events


async def _maybe_run_agentic_review(
    claim: ClaimInput, view: Any, extracted_docs: list[Any], decision: Any = None
) -> Any | None:
    """Run the advisory agent whenever it's enabled + an LLM is configured — for BOTH demo
    (eval) and upload (live) streamed claims, so the two run the identical pipeline including
    the agentic node. It stays advisory (never changes the deterministic decision), and the
    12-case eval harness uses ``run_claim`` (not this streaming path), so eval determinism is
    untouched. A failure can't break the stream — the decision has already been delivered —
    so any exception is swallowed and yields nothing."""
    settings = get_settings()
    if not (settings.enable_agentic_review and settings.has_llm):
        return None
    try:
        from app.agentic.review import run_agentic_review

        doc_types = [d.doc_type.value for d in extracted_docs]
        return await run_agentic_review(claim, view, doc_types, decision=decision)
    except Exception:  # pragma: no cover - advisory only; must never break the stream
        return None
