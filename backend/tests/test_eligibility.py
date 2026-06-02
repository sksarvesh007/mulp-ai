from __future__ import annotations

import copy

from app.engine.eligibility import evaluate_eligibility
from app.engine.view import ClaimView
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from app.schemas.extraction import LineItem


def _claim(**kw) -> ClaimInput:
    base = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
    )
    base.update(kw)
    return ClaimInput(**base)


def test_member_invalid(policy) -> None:
    r = evaluate_eligibility(_claim(member_id="ZZZ"), ClaimView(), policy)
    assert r.hard_reject and r.reasons == ["MEMBER_INVALID"]


def test_policy_mismatch(policy) -> None:
    r = evaluate_eligibility(_claim(policy_id="OTHER"), ClaimView(), policy)
    assert r.hard_reject and r.reasons == ["MEMBER_INVALID"]


def test_policy_inactive(policy) -> None:
    data = copy.deepcopy(policy.raw)
    data["policy_holder"]["renewal_status"] = "LAPSED"
    r = evaluate_eligibility(_claim(), ClaimView(), PolicyRepository(data))
    assert r.hard_reject and r.reasons == ["POLICY_INACTIVE"]


def test_below_minimum(policy) -> None:
    r = evaluate_eligibility(_claim(claimed_amount=100), ClaimView(), policy)
    assert r.hard_reject and r.reasons == ["BELOW_MINIMUM_AMOUNT"]


def test_submission_deadline_exceeded(policy) -> None:
    # late submission — a rule NOT exercised by the 12 provided cases. Treatment is
    # in-coverage (2024-05-01) so this isolates the deadline rule, not coverage.
    c = _claim(treatment_date="2024-05-01", submission_date="2024-09-01")
    r = evaluate_eligibility(c, ClaimView(condition_text="Viral Fever"), policy)
    assert r.hard_reject and r.reasons == ["SUBMISSION_DEADLINE_EXCEEDED"]


def test_treatment_date_outside_coverage(policy) -> None:
    # An impossible future / out-of-coverage treatment date is flagged before any
    # financial check — the policy was not in force on that date.
    r = evaluate_eligibility(_claim(treatment_date="2026-06-12"), ClaimView(), policy)
    assert r.hard_reject and r.reasons == ["TREATMENT_DATE_INVALID"]


def test_submission_within_window(policy) -> None:
    c = _claim(submission_date="2024-11-10")
    r = evaluate_eligibility(c, ClaimView(condition_text="Viral Fever"), policy)
    assert not r.hard_reject


def test_category_not_covered(policy) -> None:
    data = copy.deepcopy(policy.raw)
    data["opd_categories"]["consultation"]["covered"] = False
    r = evaluate_eligibility(_claim(), ClaimView(condition_text="Viral Fever"), PolicyRepository(data))
    assert r.hard_reject and r.reasons == ["CATEGORY_NOT_COVERED"]


def test_exclusion_beats_waiting(policy) -> None:
    # obesity is BOTH a waiting condition and an exclusion → exclusion must win
    v = ClaimView(condition_text="Morbid Obesity Bariatric Diet Plan")
    r = evaluate_eligibility(_claim(member_id="EMP009", treatment_date="2024-10-18"), v, policy)
    assert r.hard_reject and r.reasons == ["EXCLUDED_CONDITION"]


def test_waiting_specific_diabetes(policy) -> None:
    v = ClaimView(condition_text="Type 2 Diabetes Mellitus")
    r = evaluate_eligibility(_claim(member_id="EMP005", treatment_date="2024-10-15"), v, policy)
    assert r.hard_reject and r.reasons == ["WAITING_PERIOD"] and r.eligible_from == "2024-11-30"


def test_waiting_initial_period(policy) -> None:
    v = ClaimView(condition_text="Viral Fever")
    r = evaluate_eligibility(_claim(member_id="EMP005", treatment_date="2024-09-10"), v, policy)
    assert r.hard_reject and r.reasons == ["WAITING_PERIOD"] and r.eligible_from == "2024-10-01"


def test_waiting_pass(policy) -> None:
    r = evaluate_eligibility(_claim(), ClaimView(condition_text="Viral Fever"), policy)
    assert not r.hard_reject and r.category_covered


def test_pre_auth_mri_missing(policy) -> None:
    v = ClaimView(
        condition_text="Disc Herniation",
        tests=["MRI Lumbar Spine"],
        line_items=[LineItem(description="MRI Lumbar Spine", amount=15000)],
    )
    c = _claim(
        member_id="EMP007",
        claim_category="DIAGNOSTIC",
        treatment_date="2024-11-02",
        claimed_amount=15000,
    )
    r = evaluate_eligibility(c, v, policy)
    assert r.hard_reject and r.reasons == ["PRE_AUTH_MISSING"]


def test_pre_auth_supplied_passes(policy) -> None:
    v = ClaimView(
        condition_text="Disc Herniation",
        tests=["MRI Lumbar Spine"],
        line_items=[LineItem(description="MRI Lumbar Spine", amount=15000)],
    )
    c = _claim(
        member_id="EMP007",
        claim_category="DIAGNOSTIC",
        treatment_date="2024-11-02",
        claimed_amount=15000,
        pre_auth_reference="PA-123",
    )
    r = evaluate_eligibility(c, v, policy)
    assert not r.hard_reject


def test_pre_auth_pet_at_any_amount(policy) -> None:
    v = ClaimView(
        condition_text="Oncology follow-up",
        tests=["PET Scan"],
        line_items=[LineItem(description="PET Scan", amount=5000)],
    )
    c = _claim(claim_category="DIAGNOSTIC", treatment_date="2024-11-02", claimed_amount=5000)
    r = evaluate_eligibility(c, v, policy)
    assert r.hard_reject and r.reasons == ["PRE_AUTH_MISSING"]
