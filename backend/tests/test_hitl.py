"""Human-in-the-loop (HITL) pause/resume tests.

A ``hitl=True`` claim that trips ``fraud.manual_review`` PAUSES the LangGraph pipeline at
the ``human_review`` node (state saved by the checkpointer) → PENDING_REVIEW + a
review_request; a verdict then RESUMES the graph from that exact checkpoint to the final
decision. The default (no-checkpointer) graph never interrupts, so eval stays 12/12.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.graph import resume_claim, run_claim, run_claim_hitl
from app.main import app
from app.schemas.claim import ClaimInput
from app.schemas.decision import HumanReviewRequest, HumanReviewVerdict
from app.schemas.enums import ClaimStatus, Decision

client = TestClient(app)


def _manual_review_claim(*, hitl: bool, claim_id: str | None = None, amount: int = 2000) -> ClaimInput:
    """A well-formed claim that trips same-day fraud velocity → MANUAL_REVIEW.

    same_day_claims_limit is 2; two same-day history items + the current claim = 3 > 2.
    Two GOOD documents for the same member pass the gate, so the pipeline reaches the
    fraud stage and routes to MANUAL_REVIEW.
    """
    return ClaimInput(
        claim_id=claim_id,
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=amount,
        mode="eval",
        hitl=hitl,
        claims_history=[
            {"claim_id": "H1", "date": "2024-11-01", "amount": 500},
            {"claim_id": "H2", "date": "2024-11-01", "amount": 500},
        ],
        documents=[
            {
                "file_id": "D1",
                "actual_type": "PRESCRIPTION",
                "quality": "GOOD",
                "patient_name_on_doc": "Rajesh Kumar",
                "content": {"line_items": [{"description": "Consultation", "amount": amount}]},
            },
            {
                "file_id": "D2",
                "actual_type": "HOSPITAL_BILL",
                "quality": "GOOD",
                "patient_name_on_doc": "Rajesh Kumar",
                "content": {"line_items": [{"description": "Consultation", "amount": amount}]},
            },
        ],
    )


# ── schemas ──────────────────────────────────────────────────────────────────────
def test_review_request_default_options() -> None:
    req = HumanReviewRequest(proposed_decision="MANUAL_REVIEW", reason="x", claimed_amount=100)
    assert req.options == ["APPROVED", "REJECTED", "PARTIAL"]
    assert req.fraud_signals == []


def test_verdict_defaults() -> None:
    v = HumanReviewVerdict(action="APPROVED")
    assert v.approved_amount is None and v.reviewer == "" and v.note == ""


# ── runner: pause ──────────────────────────────────────────────────────────────────
async def test_run_claim_hitl_pauses_on_manual_review() -> None:
    result = await run_claim_hitl(_manual_review_claim(hitl=True), claim_id="HITL_PAUSE")
    assert result.decision.status == ClaimStatus.PENDING_REVIEW
    assert result.decision.decision is None
    assert result.review_request is not None
    rr = result.review_request
    assert rr.proposed_decision == "MANUAL_REVIEW"
    assert rr.claimed_amount == 2000
    assert rr.fraud_signals  # the same-day velocity signal travels to the reviewer
    assert "same-day" in rr.reason.lower()
    assert result.trace  # the trace up to the pause is preserved


# ── runner: resume (all three actions + clamping) ──────────────────────────────────
async def test_resume_applies_approved_verdict() -> None:
    await run_claim_hitl(_manual_review_claim(hitl=True), claim_id="HITL_APPROVE")
    final = await resume_claim(
        claim_id="HITL_APPROVE",
        verdict=HumanReviewVerdict(action="APPROVED", approved_amount=1500, reviewer="Asha", note="Verified records."),
    )
    d = final.decision
    assert d.status == ClaimStatus.DECIDED
    assert d.decision == Decision.APPROVED
    assert d.approved_amount == 1500
    assert any(e.step == "human_review" and e.data["reviewer"] == "Asha" for e in final.trace)
    assert any("Asha" in n and "APPROVED" in n for n in d.notes)


async def test_resume_rejected_zeroes_amount() -> None:
    await run_claim_hitl(_manual_review_claim(hitl=True), claim_id="HITL_REJECT")
    final = await resume_claim(
        claim_id="HITL_REJECT",
        verdict=HumanReviewVerdict(action="REJECTED", approved_amount=1500, reviewer="Bo"),
    )
    # REJECTED ignores any submitted amount → 0
    assert final.decision.decision == Decision.REJECTED
    assert final.decision.approved_amount == 0


async def test_resume_partial_clamps_to_claimed() -> None:
    await run_claim_hitl(_manual_review_claim(hitl=True, amount=2000), claim_id="HITL_PARTIAL")
    final = await resume_claim(
        claim_id="HITL_PARTIAL",
        verdict=HumanReviewVerdict(action="PARTIAL", approved_amount=999_999),  # over-claim → clamp
    )
    assert final.decision.decision == Decision.PARTIAL
    assert final.decision.approved_amount == 2000  # clamped to claimed_amount
    # no reviewer supplied → default label, no trailing note
    assert any("reviewer" in n for n in final.decision.notes)


async def test_resume_approved_without_amount_defaults_zero() -> None:
    await run_claim_hitl(_manual_review_claim(hitl=True), claim_id="HITL_NOAMT")
    final = await resume_claim(claim_id="HITL_NOAMT", verdict=HumanReviewVerdict(action="APPROVED", reviewer="Cy"))
    assert final.decision.decision == Decision.APPROVED
    assert final.decision.approved_amount == 0  # None → 0


# ── passthrough: the node is a no-op unless HITL + MANUAL_REVIEW ────────────────────
async def test_hitl_off_does_not_pause_manual_review() -> None:
    # MANUAL_REVIEW but hitl=False → resolves automatically, no pause / review_request
    result = await run_claim_hitl(_manual_review_claim(hitl=False), claim_id="HITL_OFF")
    assert result.decision.status == ClaimStatus.DECIDED
    assert result.decision.decision == Decision.MANUAL_REVIEW
    assert result.review_request is None


async def test_hitl_on_non_manual_review_does_not_pause(cases) -> None:
    # A clean APPROVED claim with hitl=True must NOT pause (the node passes through).
    claim = ClaimInput(**cases["TC004"]["input"], mode="eval", hitl=True)
    result = await run_claim_hitl(claim, claim_id="HITL_CLEAN")
    assert result.decision.status == ClaimStatus.DECIDED
    assert result.decision.decision == Decision.APPROVED
    assert result.review_request is None


async def test_run_claim_default_graph_does_not_crash_on_hitl_flag() -> None:
    # The default (no-checkpointer) run_claim path is what the eval harness uses. Eval inputs
    # never set hitl (→ pure passthrough), but even if one did, the default graph must not
    # crash: it simply finalises the pre-interrupt MANUAL_REVIEW decision (no resumable pause).
    result = await run_claim(_manual_review_claim(hitl=True), claim_id="HITL_DEFAULT")
    assert result.decision.status == ClaimStatus.DECIDED
    assert result.decision.decision == Decision.MANUAL_REVIEW


# ── API: submit (pause) → resume ───────────────────────────────────────────────────
def test_api_submit_hitl_then_resume() -> None:
    payload = {**_manual_review_claim(hitl=True).model_dump(mode="json"), "claim_id": "API_HITL"}
    r = client.post("/claims", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["status"] == "PENDING_REVIEW"
    assert body["review_request"]["proposed_decision"] == "MANUAL_REVIEW"

    # the pending claim is persisted and listable
    got = client.get("/claims/API_HITL")
    assert got.status_code == 200 and got.json()["decision"]["status"] == "PENDING_REVIEW"

    # resume with a human verdict → final DECIDED decision
    rr = client.post(
        "/claims/API_HITL/resume",
        json={"action": "APPROVED", "approved_amount": 1200, "reviewer": "Asha", "note": "ok"},
    )
    assert rr.status_code == 200
    decided = rr.json()
    assert decided["decision"]["status"] == "DECIDED"
    assert decided["decision"]["decision"] == "APPROVED"
    assert decided["decision"]["approved_amount"] == 1200

    # the store now reflects the finalised decision
    assert client.get("/claims/API_HITL").json()["decision"]["status"] == "DECIDED"


def test_api_resume_unknown_claim_404() -> None:
    r = client.post("/claims/NOPE/resume", json={"action": "APPROVED", "approved_amount": 100})
    assert r.status_code == 404


def test_api_resume_non_pending_claim_404(cases) -> None:
    # a normal (DECIDED) claim cannot be resumed
    client.post("/claims", json={**cases["TC004"]["input"], "mode": "eval", "claim_id": "API_DECIDED"})
    r = client.post("/claims/API_DECIDED/resume", json={"action": "APPROVED", "approved_amount": 100})
    assert r.status_code == 404


@pytest.mark.parametrize("hitl", [True, False])
def test_api_non_hitl_path_unchanged(cases, hitl: bool) -> None:
    # An APPROVED claim behaves identically with hitl on/off (it never reaches MANUAL_REVIEW).
    payload = {**cases["TC004"]["input"], "mode": "eval", "hitl": hitl, "claim_id": f"API_UNCHANGED_{hitl}"}
    r = client.post("/claims", json=payload)
    assert r.status_code == 200
    assert r.json()["decision"]["decision"] == "APPROVED"
    assert r.json()["decision"]["approved_amount"] == 1350
