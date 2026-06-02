"""The optional OpenAI-Agents-SDK reviewer: tool logic, and the NON-BLOCKING post-result
agent path (it runs OFF the critical path in stream_claim, after the decision streams, for
EVERY streamed claim — demo (eval) and upload (live) alike — when enabled). The live Agent
run is pragma-excluded (network + SDK)."""

from __future__ import annotations

import json

from app.agentic.review import (
    build_review_prompt,
    category_terms_for,
    fraud_thresholds_text,
    member_profile_for,
    required_documents_for,
)
from app.core.config import get_settings
from app.engine.view import ClaimView
from app.graph import build_graph, stream_claim
from app.graph.runner import _maybe_run_agentic_review
from app.schemas.claim import ClaimInput
from app.schemas.decision import AIAssessment, ToolCall
from app.schemas.extraction import ExtractedDocument, LineItem


def _claim(mode: str = "eval") -> ClaimInput:
    return ClaimInput(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        mode=mode,
    )


def _assessment() -> AIAssessment:
    return AIAssessment(
        summary="Looks like a routine consultation.",
        concerns=["none"],
        recommended_action="approve",
        tools_used=["member_profile", "required_documents"],
        tool_calls=[
            ToolCall(name="required_documents", arguments='{"category":"CONSULTATION"}', output="{...}"),
            ToolCall(name="member_profile", arguments='{"member_id":"EMP001"}', output="{...}"),
        ],
    )


# ── tool logic (what the agent's tools return) ──────────────────────────────────
def test_required_documents_tool() -> None:
    data = json.loads(required_documents_for("CONSULTATION"))
    assert "required" in data and isinstance(data["required"], list)


def test_member_profile_tool() -> None:
    data = json.loads(member_profile_for("EMP001"))
    assert data["member"]["name"] == "Rajesh Kumar"
    assert "Rajesh Kumar" in data["covered_names"]


def test_category_terms_tool() -> None:
    assert isinstance(json.loads(category_terms_for("DENTAL")), dict)


def test_fraud_thresholds_tool() -> None:
    assert isinstance(json.loads(fraud_thresholds_text()), dict)


def test_build_review_prompt() -> None:
    view = ClaimView(diagnosis_text="Fever", line_items=[LineItem(description="Consult", amount=1500)])
    payload = json.loads(build_review_prompt(_claim(), view, ["PRESCRIPTION", "HOSPITAL_BILL"]))
    assert payload["member_id"] == "EMP001"
    assert payload["category"] == "CONSULTATION"
    assert payload["line_items"] == ["Consult: 1500"]
    # documents present are passed so the agent never reports a provided doc as missing
    assert payload["documents_provided"] == ["PRESCRIPTION", "HOSPITAL_BILL"]


# ── the non-blocking post-result agent gate ─────────────────────────────────────
async def test_agent_skipped_when_disabled(monkeypatch) -> None:
    # default: enable_agentic_review is False → never runs (even with a key / live mode)
    monkeypatch.setenv("ENABLE_AGENTIC_REVIEW", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        out = await _maybe_run_agentic_review(_claim(mode="live"), None, [])
    finally:
        get_settings.cache_clear()
    assert out is None


async def test_agent_runs_for_eval_when_enabled(monkeypatch) -> None:
    # enabled + an LLM configured → the agent ALSO runs for an EVAL (demo) claim, so demo
    # scenarios and uploads drive the identical pipeline incl. the agentic node.
    monkeypatch.setenv("ENABLE_AGENTIC_REVIEW", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    seen: dict = {}

    async def fake_run(claim, view, documents_provided=None, *, decision=None):  # type: ignore[no-untyped-def]
        seen.update(member=claim.member_id, mode=claim.mode.value)
        return _assessment()

    monkeypatch.setattr("app.agentic.review.run_agentic_review", fake_run)
    try:
        out = await _maybe_run_agentic_review(_claim(mode="eval"), None, [])
    finally:
        get_settings.cache_clear()
    assert out is not None and out.recommended_action == "approve"
    assert seen["mode"] == "eval"  # the agent ran for the eval claim


async def test_agent_runs_for_live_when_enabled(monkeypatch) -> None:
    # enabled + LLM key + LIVE claim → the agent runs and returns its assessment
    monkeypatch.setenv("ENABLE_AGENTIC_REVIEW", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    seen: dict = {}

    async def fake_run(claim, view, documents_provided=None, *, decision=None):  # type: ignore[no-untyped-def]
        seen.update(member=claim.member_id, docs=documents_provided)
        return _assessment()

    monkeypatch.setattr("app.agentic.review.run_agentic_review", fake_run)
    docs = [ExtractedDocument(file_id="U1", doc_type="HOSPITAL_BILL")]
    try:
        out = await _maybe_run_agentic_review(_claim(mode="live"), None, docs)
    finally:
        get_settings.cache_clear()
    assert out is not None and out.recommended_action == "approve"
    # the extracted doc types are passed through so the agent never reports a provided doc missing
    assert seen["docs"] == ["HOSPITAL_BILL"]


async def test_stream_emits_ai_assessment_after_result(monkeypatch) -> None:
    """The decision streams first; the AI assessment arrives LATER as a separate event,
    proving the agent is non-blocking (off the critical path)."""
    monkeypatch.setenv("ENABLE_AGENTIC_REVIEW", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    async def fake_run(claim, view, documents_provided=None, *, decision=None):  # type: ignore[no-untyped-def]
        return _assessment()

    monkeypatch.setattr("app.agentic.review.run_agentic_review", fake_run)
    try:
        events = [e async for e in stream_claim(_claim(mode="live"), claim_id="STREAM_AI")]
    finally:
        get_settings.cache_clear()

    types = [e["type"] for e in events]
    assert "result" in types and "ai_assessment" in types
    # the ai_assessment event comes AFTER the result (decision isn't blocked on the agent)
    assert types.index("ai_assessment") > types.index("result")
    ai = next(e for e in events if e["type"] == "ai_assessment")["assessment"]
    assert ai["recommended_action"] == "approve"


async def test_stream_emits_ai_assessment_for_eval(monkeypatch) -> None:
    """Parity with the upload path: an EVAL (demo) claim ALSO streams an ai_assessment AFTER
    the decision when the agent is enabled — proving demo and upload run the same pipeline."""
    monkeypatch.setenv("ENABLE_AGENTIC_REVIEW", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    async def fake_run(claim, view, documents_provided=None, *, decision=None):  # type: ignore[no-untyped-def]
        return _assessment()

    monkeypatch.setattr("app.agentic.review.run_agentic_review", fake_run)
    try:
        events = [e async for e in stream_claim(_claim(mode="eval"), claim_id="STREAM_EVAL_AI")]
    finally:
        get_settings.cache_clear()

    types = [e["type"] for e in events]
    assert "result" in types and "ai_assessment" in types
    # same non-blocking ordering as live: the decision streams first, the assessment after
    assert types.index("ai_assessment") > types.index("result")


async def test_stream_no_ai_assessment_when_disabled() -> None:
    """With the agent disabled (the default — conftest pins the flag off), a streamed claim
    emits a decision but NEVER an ai_assessment event: the snappy, agent-free path."""
    events = [e async for e in stream_claim(_claim(mode="eval"), claim_id="STREAM_EVAL")]
    types = [e["type"] for e in events]
    assert "result" in types
    assert "ai_assessment" not in types


# ── graph topology: the agent is no longer a node ──────────────────────────────────
def test_build_graph_has_no_agentic_node() -> None:
    # the advisory agent runs off the critical path now — it must NOT be a graph node
    assert "agentic_review" not in build_graph().get_graph().nodes
