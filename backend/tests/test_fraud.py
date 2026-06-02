from __future__ import annotations

from app.engine.fraud import evaluate_fraud
from app.schemas.claim import ClaimHistoryItem, ClaimInput


def _claim(**kw) -> ClaimInput:
    base = dict(
        member_id="EMP008",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-30",
        claimed_amount=4800,
    )
    base.update(kw)
    return ClaimInput(**base)


def test_same_day_signal(policy) -> None:
    hist = [ClaimHistoryItem(date="2024-10-30") for _ in range(3)]
    r = evaluate_fraud(_claim(claims_history=hist), policy)
    assert r.manual_review
    assert r.signals[0].type.value == "SAME_DAY_CLAIMS"
    assert r.signals[0].data["count"] == 4


def test_monthly_signal(policy) -> None:
    hist = [ClaimHistoryItem(date=f"2024-10-{d:02d}") for d in range(1, 7)]
    r = evaluate_fraud(_claim(claims_history=hist), policy)
    assert any(s.type.value == "MONTHLY_CLAIMS_EXCEEDED" for s in r.signals)


def test_high_value_signal(policy) -> None:
    r = evaluate_fraud(_claim(claimed_amount=30000), policy)
    assert any(s.type.value == "HIGH_VALUE_CLAIM" for s in r.signals)


def test_alteration_signal(policy) -> None:
    r = evaluate_fraud(_claim(), policy, alteration_flags=["amount overwritten"])
    assert any(s.type.value == "DOCUMENT_ALTERATION" for s in r.signals)
    assert r.score >= 0.6


def test_clean(policy) -> None:
    r = evaluate_fraud(_claim(), policy)
    assert not r.manual_review
    assert r.signals == []
    assert r.score == 0.0
