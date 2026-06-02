from __future__ import annotations

from app.engine.decide import route_decision
from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult
from app.schemas.decision import FinancialBreakdown, FraudSignal, LineItemDecision
from app.schemas.enums import Decision, FraudSignalType, LineItemStatus
from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import ComponentFailure

DOCS = [ExtractedDocument(file_id="a")]


def _route(**kw):
    base = dict(
        eligibility=EligibilityResult(),
        fraud=FraudResult(),
        adjudication=AdjudicationResult(),
        extracted=DOCS,
        degraded=False,
        failures=[],
        claimed_amount=1_000_000,
    )
    base.update(kw)
    return route_decision(**base)


def test_hard_reject() -> None:
    e = EligibilityResult(hard_reject=True, reasons=["WAITING_PERIOD"], headline="nope", eligible_from="2024-11-30")
    d = _route(eligibility=e)
    assert d.decision.value == "REJECTED"
    assert d.rejection_reasons == ["WAITING_PERIOD"]
    assert d.eligible_from == "2024-11-30"
    assert d.confidence == 0.99  # clarity bonus


def test_manual_review_fraud() -> None:
    f = FraudResult(manual_review=True, signals=[FraudSignal(type=FraudSignalType.SAME_DAY_CLAIMS, detail="x")])
    d = _route(fraud=f)
    assert d.decision.value == "MANUAL_REVIEW"
    assert d.approved_amount is None
    assert d.fraud_signals


def test_manual_review_financial_degraded() -> None:
    fails = [ComponentFailure(component="eligibility", error_type="X", impact="")]
    d = _route(degraded=True, failures=fails)
    assert d.decision.value == "MANUAL_REVIEW"


def test_per_claim_reject() -> None:
    a = AdjudicationResult(per_claim_exceeded=True, headline="too much")
    d = _route(adjudication=a)
    assert d.decision.value == "REJECTED"
    assert d.rejection_reasons == ["PER_CLAIM_EXCEEDED"]


def test_nothing_payable() -> None:
    d = _route(adjudication=AdjudicationResult(approved_amount=0))
    assert d.decision.value == "REJECTED"
    assert d.rejection_reasons == ["NOTHING_PAYABLE"]


def test_partial() -> None:
    a = AdjudicationResult(
        approved_amount=8000,
        has_excluded=True,
        breakdown=FinancialBreakdown(base=8000, after_discount=8000, after_copay=8000, final=8000),
    )
    d = _route(adjudication=a)
    assert d.decision.value == "PARTIAL"
    assert d.approved_amount == 8000
    assert d.financial_breakdown is not None


def test_approved() -> None:
    a = AdjudicationResult(
        approved_amount=1350,
        breakdown=FinancialBreakdown(base=1500, after_discount=1500, copay=150, after_copay=1350, final=1350),
    )
    d = _route(adjudication=a)
    assert d.decision.value == "APPROVED"
    assert d.approved_amount == 1350


def test_degraded_non_financial_stays_approved() -> None:
    fails = [ComponentFailure(component="fraud", error_type="X", impact="")]
    a = AdjudicationResult(
        approved_amount=4000,
        breakdown=FinancialBreakdown(base=4000, after_discount=4000, after_copay=4000, final=4000),
    )
    d = _route(degraded=True, failures=fails, adjudication=a)
    assert d.decision.value == "APPROVED"
    assert d.degraded
    assert d.confidence < 0.95
    assert any("manual review recommended" in n.lower() for n in d.notes)


def test_route_corrects_approved_over_claimed() -> None:
    # Safety net: even if adjudication somehow returns approved > claimed, the router clamps it.
    a = AdjudicationResult(
        approved_amount=8000,
        has_excluded=True,
        line_items=[
            LineItemDecision(description="Root Canal", amount=8000, status=LineItemStatus.COVERED, approved_amount=8000)
        ],
        breakdown=FinancialBreakdown(base=8000, after_discount=8000, after_copay=8000, final=8000),
    )
    d = _route(adjudication=a, claimed_amount=5000)
    assert d.decision == Decision.PARTIAL
    assert d.approved_amount == 5000
    assert d.financial_breakdown.final == 5000
    assert any("Invariant check corrected" in n for n in d.notes)


def test_route_correction_without_breakdown() -> None:
    a = AdjudicationResult(approved_amount=9000, breakdown=None)
    d = _route(adjudication=a, claimed_amount=4000)
    assert d.approved_amount == 4000
    assert any("Invariant check corrected" in n for n in d.notes)
