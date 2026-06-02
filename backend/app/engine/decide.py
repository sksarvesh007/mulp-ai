"""The decision router — the single authority that maps stage results to a final
``ClaimDecision`` using the precedence ladder (PLAN.md §4):

  1. eligibility hard-reject            → REJECTED
  2. fraud OR financial-component fail  → MANUAL_REVIEW
  3. per-claim exceeded                 → REJECTED
  4. nothing payable                    → REJECTED
  5. some line items excluded           → PARTIAL
  6. otherwise                          → APPROVED

Degradation lowers confidence and adds a note; it only forces MANUAL_REVIEW when a
*financially-relevant* component failed (so TC011, whose fraud component fails, stays
APPROVED).
"""

from __future__ import annotations

from app.engine.confidence import compute_confidence
from app.engine.invariants import check_invariants
from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult
from app.schemas.decision import ClaimDecision
from app.schemas.enums import ClaimStatus, Decision, RejectionReason
from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import ComponentFailure

# A failure in any of these means the money/coverage path is unreliable → manual review.
FINANCIAL_COMPONENTS = {
    "extract",
    "extract_doc",
    "extract_single_doc",
    "collect_extractions",
    "merge_extractions",
    "eligibility",
    "adjudicate",
}


def route_decision(
    *,
    eligibility: EligibilityResult,
    fraud: FraudResult,
    adjudication: AdjudicationResult,
    extracted: list[ExtractedDocument],
    degraded: bool,
    failures: list[ComponentFailure],
    claimed_amount: int = 0,
) -> ClaimDecision:
    financial_degraded = any(f.component in FINANCIAL_COMPONENTS for f in failures)
    notes: list[str] = []
    if degraded:
        skipped = ", ".join(sorted({f.component for f in failures})) or "a component"
        notes.append(
            f"Manual review recommended: the {skipped} step(s) could not run and were skipped, "
            f"so confidence is reduced."
        )

    def finish(
        decision: Decision | None,
        *,
        approved_amount: int | None,
        reason: str | None,
        manual_review: bool,
        clarity_bonus: bool,
        reasons: list[str] | None = None,
        eligible_from: str | None = None,
    ) -> ClaimDecision:
        conf = compute_confidence(
            extracted,
            manual_review=manual_review,
            clarity_bonus=clarity_bonus,
            num_failures=len(failures),
        )
        cd = ClaimDecision(
            decision=decision,
            status=ClaimStatus.DECIDED,
            approved_amount=approved_amount,
            rejection_reasons=reasons or [],
            line_items=adjudication.line_items,
            financial_breakdown=adjudication.breakdown if decision in (Decision.APPROVED, Decision.PARTIAL) else None,
            fraud_signals=fraud.signals,
            eligible_from=eligible_from,
            reason=reason,
            confidence=conf.final,
            confidence_breakdown=conf,
            degraded=degraded,
            component_failures=list(failures),
            notes=list(notes),
        )
        # Safety net: catch any logic failure (e.g. approved > claimed) and correct it.
        violations = check_invariants(cd, claimed_amount)
        if violations:
            cd.approved_amount = max(0, min(cd.approved_amount or 0, claimed_amount))
            if cd.financial_breakdown is not None:
                cd.financial_breakdown.final = cd.approved_amount
            cd.notes.append("⚠ Invariant check corrected the decision: " + "; ".join(violations))
        return cd

    # 1. eligibility hard-reject
    if eligibility.hard_reject:
        return finish(
            Decision.REJECTED,
            approved_amount=0,
            reason=eligibility.headline,
            manual_review=False,
            clarity_bonus=True,
            reasons=eligibility.reasons,
            eligible_from=eligibility.eligible_from,
        )

    # 2. manual review (fraud signals OR a financially-relevant component failed)
    if fraud.manual_review or financial_degraded:
        if fraud.signals:
            reason = "Routed to manual review due to anomaly signals: " + "; ".join(s.detail for s in fraud.signals)
        else:
            reason = "Routed to manual review: a processing component failed; an automatic decision is not safe."
        return finish(
            Decision.MANUAL_REVIEW,
            approved_amount=None,
            reason=reason,
            manual_review=True,
            clarity_bonus=False,
        )

    # 3. per-claim exceeded
    if adjudication.per_claim_exceeded:
        return finish(
            Decision.REJECTED,
            approved_amount=0,
            reason=adjudication.headline,
            manual_review=False,
            clarity_bonus=True,
            reasons=[RejectionReason.PER_CLAIM_EXCEEDED.value],
        )

    # 4. nothing payable
    if adjudication.approved_amount <= 0:
        return finish(
            Decision.REJECTED,
            approved_amount=0,
            reason="No payable amount remains after applying policy rules.",
            manual_review=False,
            clarity_bonus=False,
            reasons=[RejectionReason.NOTHING_PAYABLE.value],
        )

    # 5/6. partial or approved
    decision = Decision.PARTIAL if adjudication.has_excluded else Decision.APPROVED
    return finish(
        decision,
        approved_amount=adjudication.approved_amount,
        reason=adjudication.headline,
        manual_review=False,
        clarity_bonus=False,
    )
