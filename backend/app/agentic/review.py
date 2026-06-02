"""Optional OpenAI-Agents-SDK reviewer — an advisory perception node.

An ``Agent`` (running on the configured OpenAI model) is given **policy tools** it can
call to look up document requirements, member details, category coverage terms and fraud
thresholds, then it returns a plain-language assessment of the claim.

It is **advisory only**: the assessment never changes the deterministic decision (LLMs
perceive; Python decides). Enabled via ``settings.enable_agentic_review``. The tool *logic*
is pure and unit-tested; the Agent run itself is network/SDK-bound and pragma-excluded.
"""

from __future__ import annotations

import json
from typing import Any

from app.deps import get_policy
from app.schemas.decision import AIAssessment, ToolCall

_INSTRUCTIONS = (
    "You are a friendly health-insurance claims assistant. The system has ALREADY decided this "
    "claim using deterministic policy rules — you are ADVISORY ONLY and must NOT change, "
    "second-guess, or re-decide it. Your job is to (1) explain the decision to the member in "
    "plain, warm, non-technical language, and (2) tell them clearly what to do next.\n\n"
    "The input includes the system's `decision`, `reason`, `rejection_reasons`, `approved_amount` "
    "and `eligible_from`. Treat that decision as FINAL and CORRECT — your explanation must be "
    "consistent with it (e.g. never say 'approve' for a rejected claim). Use your tools to add "
    "accurate context so the member understands WHY (the documents a category needs, the member's "
    "coverage, the waiting periods, co-pay/sub-limit rules, fraud thresholds). Never invent "
    "amounts, dates, or facts, and do NOT redo the money math — the engine already computed the "
    "final amount.\n\n"
    "Turn the decision into a concrete next step, e.g.: APPROVED → reassure them, nothing to do; "
    "PARTIAL → explain what was and wasn't covered; REJECTED for a waiting period → tell them the "
    "date they become eligible (`eligible_from`) and to resubmit then; REJECTED for an exclusion → "
    "explain the treatment isn't covered; REJECTED for a per-claim/annual limit → explain the cap; "
    "MANUAL_REVIEW → a human will verify, no action needed yet; a document problem → which document "
    "to re-upload and how.\n\n"
    "Respond with ONLY a JSON object (no markdown, no prose) of the form: "
    '{"summary": "<2-3 plain, friendly sentences explaining the outcome to the member>", '
    '"concerns": ["<short caveat the member should know>", ...], '
    '"recommended_action": "<the single concrete next step the member should take>"}.'
)


# ── tool logic (pure, unit-tested) ──────────────────────────────────────────────
def required_documents_for(category: str) -> str:
    """Document types the policy requires for a claim category."""
    return json.dumps(get_policy().document_requirements(category))


def member_profile_for(member_id: str) -> str:
    """The member's profile plus the names covered under their policy."""
    p = get_policy()
    return json.dumps({"member": p.member(member_id), "covered_names": p.covered_names_for(member_id)})


def category_terms_for(category: str) -> str:
    """Coverage terms for a category: co-pay %, sub-limit, per-claim cap, etc."""
    return json.dumps(get_policy().category_optional(category) or {})


def fraud_thresholds_text() -> str:
    """Fraud / anomaly thresholds (same-day count, high-value amount, …)."""
    return json.dumps(get_policy().fraud_thresholds)


def build_review_prompt(
    claim: Any, view: Any, documents_provided: list[str] | None = None, *, decision: Any = None
) -> str:
    """Assemble the claim + extracted view + the system's DECISION into the agent's input
    (deterministic, tested). The agent explains the decision and advises the member, so it
    must see the outcome (decision/reason/amounts/eligibility) — getattr keeps it None-safe.

    ``documents_provided`` are the document types already attached, so the agent never
    wrongly reports a present document as missing.
    """
    line_items = [f"{x.description}: {x.amount}" for x in getattr(view, "line_items", []) or []]
    return json.dumps(
        {
            "member_id": claim.member_id,
            "category": claim.claim_category.value,
            "claimed_amount": claim.claimed_amount,
            "treatment_date": str(claim.treatment_date) if claim.treatment_date else None,
            "hospital_name": claim.hospital_name,
            "documents_provided": documents_provided or [],
            "diagnosis": getattr(view, "diagnosis_text", ""),
            "treatment": getattr(view, "treatment_text", ""),
            "line_items": line_items,
            "bill_total": getattr(view, "bill_total", None),
            "patient_names": getattr(view, "patient_names", []),
            # the system's final decision — the agent EXPLAINS this, never overrides it
            "decision": getattr(getattr(decision, "decision", None), "value", None),
            "status": getattr(getattr(decision, "status", None), "value", None),
            "reason": getattr(decision, "reason", None),
            "rejection_reasons": getattr(decision, "rejection_reasons", None),
            "approved_amount": getattr(decision, "approved_amount", None),
            "eligible_from": getattr(decision, "eligible_from", None),
        },
        default=str,
    )


async def run_agentic_review(  # pragma: no cover - network + SDK
    claim: Any, view: Any, documents_provided: list[str] | None = None, *, decision: Any = None
) -> AIAssessment | None:
    """Run the Agents-SDK reviewer. Returns ``None`` if no model is configured."""
    from agents import (
        Agent,
        OpenAIChatCompletionsModel,
        Runner,
        function_tool,
        set_tracing_disabled,
    )
    from openai import AsyncOpenAI

    from app.core.config import get_settings
    from app.llm.openai_client import extract_json

    s = get_settings()
    if not s.openai_api_key:
        return None
    # Keep the Agents SDK tracing ON when observability is enabled, so the OpenInference
    # instrumentor can export the agent's generations + tool calls to Langfuse. Otherwise
    # disable it.
    set_tracing_disabled(not s.enable_observability)

    @function_tool
    def required_documents(category: str) -> str:
        """Document types the policy requires for a claim category."""
        return required_documents_for(category)

    @function_tool
    def member_profile(member_id: str) -> str:
        """The member's profile and the names covered under their policy."""
        return member_profile_for(member_id)

    @function_tool
    def category_terms(category: str) -> str:
        """Coverage terms for a category (co-pay %, sub-limit, per-claim cap)."""
        return category_terms_for(category)

    @function_tool
    def fraud_thresholds() -> str:
        """Fraud / anomaly thresholds for the policy."""
        return fraud_thresholds_text()

    client = AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )
    agent = Agent(
        name="Claim reviewer",
        instructions=_INSTRUCTIONS,
        tools=[required_documents, member_profile, category_terms, fraud_thresholds],
        model=OpenAIChatCompletionsModel(model=s.openai_model, openai_client=client),
    )
    # Let the agent finish in free text and parse the JSON ourselves (same approach as
    # extraction) — robust to any prose/fences and avoids the SDK's strict-mode constraints.
    prompt = build_review_prompt(claim, view, documents_provided, decision=decision)
    result = await Runner.run(agent, prompt, max_turns=6)
    text = str(result.final_output or "")
    data = extract_json(text)

    # Capture each tool the agent invoked (name + args), paired in order with its output,
    # so the pipeline trace can show exactly which tools ran.
    requests = [
        (str(getattr(it.raw_item, "name", "")), str(getattr(it.raw_item, "arguments", "")))
        for it in result.new_items
        if getattr(it, "type", "") == "tool_call_item"
    ]
    outputs = [
        str(getattr(it, "output", "")) for it in result.new_items if getattr(it, "type", "") == "tool_call_output_item"
    ]
    tool_calls = [
        ToolCall(name=name, arguments=args, output=outputs[i] if i < len(outputs) else "")
        for i, (name, args) in enumerate(requests)
        if name
    ]
    return AIAssessment(
        summary=str(data.get("summary") or text[:600]),
        concerns=[str(c) for c in (data.get("concerns") or [])],
        recommended_action=str(data.get("recommended_action") or ""),
        tools_used=sorted({tc.name for tc in tool_calls}),
        tool_calls=tool_calls,
    )
