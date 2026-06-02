from __future__ import annotations

from app.engine.invariants import check_invariants
from app.schemas.decision import ClaimDecision, FinancialBreakdown, LineItemDecision
from app.schemas.enums import ClaimStatus, Decision, LineItemStatus


def _approved(amount, **kw) -> ClaimDecision:
    return ClaimDecision(decision=Decision.APPROVED, status=ClaimStatus.DECIDED, approved_amount=amount, **kw)


def test_clean_decision_has_no_violations() -> None:
    assert check_invariants(_approved(1350), 1500) == []


def test_approved_over_claimed_flagged() -> None:
    v = check_invariants(_approved(8000), 5000)
    assert any("exceeds the claimed amount" in x for x in v)


def test_negative_amount_flagged() -> None:
    assert any("negative" in x for x in check_invariants(_approved(-10), 5000))


def test_line_item_over_billed_flagged() -> None:
    d = _approved(
        100,
        line_items=[LineItemDecision(description="X", amount=50, status=LineItemStatus.COVERED, approved_amount=80)],
    )
    assert any("exceeds billed" in x for x in check_invariants(d, 1000))


def test_breakdown_mismatch_flagged() -> None:
    d = _approved(100, financial_breakdown=FinancialBreakdown(base=100, after_discount=100, after_copay=100, final=200))
    assert any("breakdown final" in x for x in check_invariants(d, 1000))


def test_rejected_with_amount_flagged() -> None:
    d = ClaimDecision(decision=Decision.REJECTED, status=ClaimStatus.DECIDED, approved_amount=500)
    assert any("must not approve" in x for x in check_invariants(d, 1000))


def test_approved_missing_amount_flagged() -> None:
    d = ClaimDecision(decision=Decision.APPROVED, status=ClaimStatus.DECIDED, approved_amount=None)
    assert any("missing" in x for x in check_invariants(d, 1000))


def test_rejected_zero_amount_ok() -> None:
    d = ClaimDecision(decision=Decision.REJECTED, status=ClaimStatus.DECIDED, approved_amount=0)
    assert check_invariants(d, 1000) == []


def test_valid_complex_decision_ok() -> None:
    d = _approved(
        8000,
        line_items=[
            LineItemDecision(description="RC", amount=8000, status=LineItemStatus.COVERED, approved_amount=8000)
        ],
        financial_breakdown=FinancialBreakdown(base=8000, after_discount=8000, after_copay=8000, final=8000),
    )
    assert check_invariants(d, 12000) == []


def test_decision_none_has_no_violations() -> None:
    d = ClaimDecision(decision=None, status=ClaimStatus.NEEDS_MEMBER_ACTION)
    assert check_invariants(d, 1000) == []
