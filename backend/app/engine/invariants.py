"""Post-adjudication invariant checks.

A defensive safety net: even though the financial engine clamps correctly, these
checks catch any logic failure (e.g. ``approved_amount > claimed_amount``,
line-item approved > billed, a breakdown that doesn't sum, or a REJECTED decision
that somehow approves money) so it surfaces as a correction + loud note rather than a
silent wrong amount.
"""

from __future__ import annotations

from app.schemas.decision import ClaimDecision
from app.schemas.enums import Decision


def check_invariants(decision: ClaimDecision, claimed_amount: int) -> list[str]:
    """Return a list of invariant-violation messages (empty when the decision is sound)."""
    violations: list[str] = []
    amount = decision.approved_amount

    if decision.decision in (Decision.APPROVED, Decision.PARTIAL):
        if amount is None:
            violations.append("approved_amount is missing for an approved/partial decision")
        else:
            if amount < 0:
                violations.append(f"approved_amount {amount} is negative")
            if amount > claimed_amount:
                violations.append(f"approved_amount {amount} exceeds the claimed amount {claimed_amount}")
        for li in decision.line_items:
            if li.approved_amount > li.amount:
                violations.append(
                    f"line item '{li.description}' approved {li.approved_amount} exceeds billed {li.amount}"
                )
        fb = decision.financial_breakdown
        if fb is not None and amount is not None and fb.final != amount:
            violations.append(f"financial breakdown final {fb.final} != approved_amount {amount}")
    elif decision.decision in (Decision.REJECTED, Decision.MANUAL_REVIEW):
        if amount not in (None, 0):
            violations.append(f"{decision.decision.value} must not approve an amount (got {amount})")

    return violations
