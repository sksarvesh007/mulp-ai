from __future__ import annotations

from app.engine.adjudication import adjudicate
from app.engine.results import EligibilityResult, FraudResult
from app.engine.view import ClaimView
from app.schemas.claim import ClaimInput
from app.schemas.extraction import LineItem

ELIG = EligibilityResult()
FRAUD = FraudResult()


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


def test_skipped_on_hard_reject(policy) -> None:
    r = adjudicate(_claim(), ClaimView(), policy, EligibilityResult(hard_reject=True), FRAUD)
    assert r.skipped


def test_skipped_on_manual_review(policy) -> None:
    r = adjudicate(_claim(), ClaimView(), policy, ELIG, FraudResult(manual_review=True))
    assert r.skipped


def test_consultation_copay(policy) -> None:
    r = adjudicate(_claim(claimed_amount=1500), ClaimView(), policy, ELIG, FRAUD)
    assert r.approved_amount == 1350
    assert r.breakdown.copay == 150
    assert not r.has_excluded and not r.per_claim_exceeded


def test_network_discount_applied_before_copay(policy) -> None:
    # Order proof: co-pay is 10% of the POST-discount ₹3,600 (=₹360), not of ₹4,500 (=₹450).
    v = ClaimView(hospital_name="Apollo Hospitals")
    c = _claim(
        member_id="EMP010",
        claimed_amount=4500,
        hospital_name="Apollo Hospitals",
        ytd_claims_amount=8000,
    )
    r = adjudicate(c, v, policy, ELIG, FRAUD)
    assert r.approved_amount == 3240
    assert r.breakdown.after_discount == 3600
    assert r.breakdown.copay == 360


def test_per_claim_exceeded_full_reject(policy) -> None:
    r = adjudicate(_claim(claimed_amount=7500, ytd_claims_amount=10000), ClaimView(), policy, ELIG, FRAUD)
    assert r.per_claim_exceeded
    assert r.approved_amount == 0


def test_dental_partial(policy) -> None:
    v = ClaimView(
        line_items=[
            LineItem(description="Root Canal Treatment", amount=8000),
            LineItem(description="Teeth Whitening", amount=4000),
        ]
    )
    c = _claim(member_id="EMP002", claim_category="DENTAL", claimed_amount=12000)
    r = adjudicate(c, v, policy, ELIG, FRAUD)
    assert r.has_excluded and r.approved_amount == 8000 and not r.per_claim_exceeded
    statuses = {li.description: li.status.value for li in r.line_items}
    assert statuses["Root Canal Treatment"] == "COVERED"
    assert statuses["Teeth Whitening"] == "EXCLUDED"


def test_dental_sub_limit_cap(policy) -> None:
    v = ClaimView(line_items=[LineItem(description="Root Canal Treatment", amount=15000)])
    c = _claim(member_id="EMP002", claim_category="DENTAL", claimed_amount=15000)
    r = adjudicate(c, v, policy, ELIG, FRAUD)
    assert r.approved_amount == 10000
    assert r.breakdown.clamps


def test_annual_opd_cap(policy) -> None:
    c = _claim(claimed_amount=4000, ytd_claims_amount=48000)
    r = adjudicate(c, ClaimView(), policy, ELIG, FRAUD)
    # base 4000 → 10% co-pay → 3600; remaining OPD = 2000 → capped
    assert r.approved_amount == 2000
    assert any("annual OPD" in c for c in r.breakdown.clamps)


def test_alt_medicine_plain_approval(policy) -> None:
    v = ClaimView(
        line_items=[
            LineItem(description="Panchakarma Therapy", amount=3000),
            LineItem(description="Consultation", amount=1000),
        ]
    )
    c = _claim(member_id="EMP006", claim_category="ALTERNATIVE_MEDICINE", claimed_amount=4000)
    r = adjudicate(c, v, policy, ELIG, FRAUD)
    assert r.approved_amount == 4000 and not r.has_excluded


def test_never_approves_more_than_claimed(policy) -> None:
    # Dental bill (covered ₹8000) but member claimed only ₹5000 → approve at most ₹5000.
    v = ClaimView(line_items=[LineItem(description="Root Canal Treatment", amount=8000)])
    c = _claim(member_id="EMP002", claim_category="DENTAL", claimed_amount=5000)
    r = adjudicate(c, v, policy, ELIG, FRAUD)
    assert r.approved_amount == 5000
    assert any("claimed amount" in cl for cl in r.breakdown.clamps)
