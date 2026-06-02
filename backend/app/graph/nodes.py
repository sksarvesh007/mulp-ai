"""LangGraph nodes. Each wraps a deterministic engine function (or an LLM extractor)
and is decorated with ``@resilient_node`` so a failure becomes degraded state, never a
crash. Custom progress events are streamed via a guarded stream writer."""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.types import Send, interrupt

from app.core.money import fmt_inr
from app.deps import get_extractor, get_policy
from app.engine import (
    adjudicate,
    build_claim_view,
    evaluate_eligibility,
    evaluate_fraud,
    route_decision,
    verify_claim_consistency,
    verify_documents,
)
from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult
from app.engine.trace_util import ev
from app.engine.view import ClaimView
from app.graph.state import ClaimState
from app.observability.logs import get_logger
from app.schemas.decision import ClaimDecision, HumanReviewRequest, HumanReviewVerdict
from app.schemas.enums import ClaimStatus, Decision, TraceStatus
from app.schemas.trace import ComponentFailure

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

log = get_logger("app.graph.node")


def _writer() -> Callable[[dict[str, Any]], None]:
    """Return the stream writer, or a no-op when not inside a streaming run."""
    try:
        w = get_stream_writer()
        return w if callable(w) else (lambda _m: None)
    except Exception:
        return lambda _m: None


# Human-readable labels for the degradation notice (never expose internal node names raw).
_FRIENDLY_NODE = {
    "intake": "Intake",
    "classify": "Document classification",
    "extract": "Document extraction",
    "merge": "Data merge",
    "consistency": "Claim-document consistency",
    "eligibility": "Eligibility checks",
    "fraud": "Fraud & anomaly screening",
    "adjudication": "Adjudication",
    "score": "Adjudication",
    "confidence": "Confidence scoring",
    "finalize": "Finalisation",
}


def _friendly_node(name: str) -> str:
    return _FRIENDLY_NODE.get(name, name.replace("_", " ").capitalize())


def resilient_node(name: str) -> Callable[..., Any]:
    """Wrap a node so an exception is captured as a ComponentFailure + degraded=True
    and the graph continues with a valid partial-state delta."""

    def deco(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            write = _writer()
            start = time.perf_counter()
            try:
                write({"event": "node_start", "node": name})
                out = await fn(state)
                write({"event": "node_done", "node": name})
                log.info("node.done", node=name, elapsed_ms=round((time.perf_counter() - start) * 1000, 1))
                return out or {}
            except Exception as exc:  # graceful degradation (TC011)
                # Keep the raw exception for logs/observability, but NEVER surface a
                # `RuntimeError: ...` string to the UI — show a clean degradation notice.
                msg = f"{type(exc).__name__}: {exc}"
                write({"event": "node_error", "node": name, "error": msg})
                # A node failure degrades the pipeline rather than crashing it — log it at
                # ERROR (with the traceback) so the swallowed exception is never invisible.
                log.error(
                    "node.failed",
                    node=name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
                    exc_info=True,
                )
                return {
                    "failures": [
                        ComponentFailure(
                            component=name,
                            error_type=type(exc).__name__,
                            impact="was unavailable and was skipped — the claim was processed with "
                            "reduced automated checks and flagged for manual review",
                            recoverable=True,
                        )
                    ],
                    "degraded": True,
                    "trace_events": [
                        ev(
                            name,
                            TraceStatus.FAIL,
                            f"{_friendly_node(name)} was temporarily unavailable and was skipped — "
                            "the claim continued with reduced automated checks (flagged for manual review).",
                            error_type=type(exc).__name__,  # technical detail retained in trace data, not shown
                        )
                    ],
                }

        return wrapper

    return deco


# ── intake ────────────────────────────────────────────────────────────────────
@resilient_node("intake")
async def intake(state: dict[str, Any]) -> dict[str, Any]:
    claim = state["claim"]
    return {
        "trace_events": [
            ev(
                "intake",
                TraceStatus.INFO,
                f"Claim received for member {claim.member_id}, category {claim.claim_category.value}, "
                f"claimed {fmt_inr(claim.claimed_amount)}.",
                member_id=claim.member_id,
                category=claim.claim_category.value,
            )
        ]
    }


def fan_out_classify(state: dict[str, Any]) -> list[Send]:
    claim = state["claim"]
    return [Send("classify_doc", {"doc": d, "mode": claim.mode.value}) for d in claim.documents]


@resilient_node("classify_doc")
async def classify_doc(state: dict[str, Any]) -> dict[str, Any]:
    doc, mode = state["doc"], state["mode"]
    result = await get_extractor(mode).classify(doc)
    return {
        "classified_docs": [result],
        "trace_events": [
            ev(
                "classify_doc",
                TraceStatus.PASS,
                f"Classified {doc.file_id} as {result.doc_type.value} (quality {result.quality.value}).",
                file_id=doc.file_id,
                doc_type=result.doc_type.value,
            )
        ],
    }


# ── document-verification gate ─────────────────────────────────────────────────
@resilient_node("gate")
async def gate(state: dict[str, Any]) -> dict[str, Any]:
    result = verify_documents(state["claim"], state.get("classified_docs", []), get_policy())
    return {"gate_result": result, "trace_events": result.trace}


def route_after_gate(state: dict[str, Any]) -> str | list[Send]:
    gate_result = state.get("gate_result")
    if gate_result is None or not gate_result.passed:
        return "format_blocker"
    claim = state["claim"]
    return [Send("extract_doc", {"doc": d, "mode": claim.mode.value}) for d in claim.documents]


@resilient_node("format_blocker")
async def format_blocker(state: dict[str, Any]) -> dict[str, Any]:
    problem = state["gate_result"].problem
    decision = ClaimDecision(
        decision=None,
        status=ClaimStatus.NEEDS_MEMBER_ACTION,
        document_problem=problem,
        reason=problem.message if problem else "Documents require attention.",
    )
    return {"decision": decision}


# ── claim ↔ document consistency (post-extraction, pre-adjudication) ─────────────
@resilient_node("consistency")
async def consistency(state: dict[str, Any]) -> dict[str, Any]:
    """Cross-check the member's DECLARED claim details against the extracted documents.
    On a mismatch it sets a failed ``gate_result`` so the existing ``format_blocker``
    builds the same member-action decision; on a match it only emits a trace event and the
    gate's earlier PASS result is left untouched, so the claim proceeds to adjudication."""
    result = verify_claim_consistency(state["claim"], state.get("extracted_docs", []), state.get("view"))
    out: dict[str, Any] = {"trace_events": result.trace}
    if not result.passed:
        out["gate_result"] = result
    return out


def route_after_consistency(state: dict[str, Any]) -> str:
    # The gate's own result was PASS to reach this node; only a consistency MISMATCH
    # replaces it with a non-passed result, which routes to the member-action blocker.
    gate_result = state.get("gate_result")
    if gate_result is not None and not gate_result.passed:
        return "format_blocker"
    return "eligibility"


# ── extraction ─────────────────────────────────────────────────────────────────
@resilient_node("extract_doc")
async def extract_doc(state: dict[str, Any]) -> dict[str, Any]:
    doc, mode = state["doc"], state["mode"]
    result = await get_extractor(mode).extract(doc)
    return {
        "extracted_docs": [result],
        "trace_events": [
            ev(
                "extract_doc",
                TraceStatus.PASS,
                f"Extracted fields from {doc.file_id}.",
                file_id=doc.file_id,
            )
        ],
    }


@resilient_node("merge_extractions")
async def merge_extractions(state: dict[str, Any]) -> dict[str, Any]:
    extracted = state.get("extracted_docs", [])
    view = build_claim_view(extracted)
    return {
        "view": view,
        "trace_events": [
            ev(
                "merge_extractions",
                TraceStatus.INFO,
                f"Merged {len(extracted)} document(s) into a claim view.",
            )
        ],
    }


# ── rule stages ────────────────────────────────────────────────────────────────
@resilient_node("eligibility")
async def eligibility(state: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_eligibility(state["claim"], state.get("view") or ClaimView(), get_policy())
    return {"eligibility_result": result, "trace_events": result.trace}


@resilient_node("fraud")
async def fraud(state: dict[str, Any]) -> dict[str, Any]:
    claim = state["claim"]
    if claim.simulate_component_failure:  # TC011 injection
        raise RuntimeError("SimulatedFailure: fraud/anomaly component is unavailable")
    result = evaluate_fraud(claim, get_policy())
    return {"fraud_result": result, "trace_events": result.trace}


@resilient_node("adjudicate")
async def adjudicate_node(state: dict[str, Any]) -> dict[str, Any]:
    result = adjudicate(
        state["claim"],
        state.get("view") or ClaimView(),
        get_policy(),
        state.get("eligibility_result") or EligibilityResult(),
        state.get("fraud_result") or FraudResult(),
    )
    return {"adjudication_result": result, "trace_events": result.trace}


@resilient_node("score_route")
async def score_route(state: dict[str, Any]) -> dict[str, Any]:
    decision = route_decision(
        eligibility=state.get("eligibility_result") or EligibilityResult(),
        fraud=state.get("fraud_result") or FraudResult(),
        adjudication=state.get("adjudication_result") or AdjudicationResult(),
        extracted=state.get("extracted_docs", []),
        degraded=state.get("degraded", False),
        failures=state.get("failures", []),
        claimed_amount=state["claim"].claimed_amount,
    )
    # The advisory AI assessment is NOT computed here: the agent runs OFF the critical path
    # (after the decision streams) and its assessment arrives as a separate `ai_assessment`
    # stream event, so the decision never waits on it.
    return {"decision": decision}


# ── human-in-the-loop review ─────────────────────────────────────────────────────
# NOT wrapped with @resilient_node: interrupt() raises a GraphInterrupt (an Exception
# subclass) that MUST propagate to pause the graph — resilient_node would catch it and
# turn the pause into a degraded state. The ClaimState param keeps add_node's type happy.
async def human_review(state: ClaimState) -> dict[str, Any]:
    """Pause the graph for a human when (and only when) a HITL claim was routed to
    MANUAL_REVIEW. For every other claim this is a pure pass-through, so the default
    graph (no checkpointer, eval inputs) never calls ``interrupt()`` and is unchanged.

    On resume the human's verdict is applied to the decision: action becomes the final
    decision, status → DECIDED, approved_amount clamped to [0, claimed_amount] (0 for a
    rejection), with a trace event recording the reviewer, action and note.
    """
    claim = state["claim"]
    decision = state.get("decision")
    if not (claim.hitl and decision is not None and decision.decision == Decision.MANUAL_REVIEW):
        return {}

    write = _writer()
    write({"event": "human_review_pause"})
    # PAUSE: the checkpointer saves the full state here; ainvoke returns control with an
    # __interrupt__ payload. A later Command(resume=...) re-enters this node and interrupt()
    # returns the resume value (the human's verdict).
    raw = interrupt(
        HumanReviewRequest(
            proposed_decision=Decision.MANUAL_REVIEW.value,
            reason=decision.reason or "Routed to manual review.",
            fraud_signals=decision.fraud_signals,
            claimed_amount=claim.claimed_amount,
        ).model_dump()
    )

    verdict = HumanReviewVerdict.model_validate(raw)
    action = Decision(verdict.action)
    approved = 0 if action == Decision.REJECTED else max(0, min(verdict.approved_amount or 0, claim.claimed_amount))
    decision.decision = action
    decision.status = ClaimStatus.DECIDED
    decision.approved_amount = approved
    reviewer = verdict.reviewer or "reviewer"
    headline = f"Human review by {reviewer}: {action.value}."
    decision.reason = headline
    note = f"{headline}{(' ' + verdict.note) if verdict.note else ''} Approved amount {fmt_inr(approved)}."
    decision.notes = [*decision.notes, note]
    write({"event": "human_review_resume", "action": action.value})
    return {
        "decision": decision,
        "trace_events": [
            ev(
                "human_review",
                TraceStatus.INFO,
                f"{headline} Approved {fmt_inr(approved)}." + (f" Note: {verdict.note}" if verdict.note else ""),
                reviewer=reviewer,
                action=action.value,
                approved_amount=approved,
                note=verdict.note,
            )
        ],
    }


@resilient_node("finalize")
async def finalize(state: dict[str, Any]) -> dict[str, Any]:
    decision = state.get("decision")
    label = (
        decision.decision.value
        if decision and decision.decision
        else (decision.status.value if decision else "UNKNOWN")
    )
    return {"trace_events": [ev("finalize", TraceStatus.INFO, f"Decision finalized: {label}.")]}
