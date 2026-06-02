"""Stage 6 — Fraud / anomaly detection. Triggers route to MANUAL_REVIEW; they
NEVER auto-reject (TC009). Deterministic counters read thresholds from the policy."""

from __future__ import annotations

from app.engine.results import FraudResult
from app.engine.trace_util import ev
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from app.schemas.decision import FraudSignal
from app.schemas.enums import FraudSignalType, TraceStatus

# Signal weights → an aggregate fraud_score (compared against the policy threshold).
_WEIGHTS = {
    FraudSignalType.SAME_DAY_CLAIMS: 0.5,
    FraudSignalType.MONTHLY_CLAIMS_EXCEEDED: 0.3,
    FraudSignalType.HIGH_VALUE_CLAIM: 0.5,
    FraudSignalType.DOCUMENT_ALTERATION: 0.6,
}


def evaluate_fraud(
    claim: ClaimInput,
    policy: PolicyRepository,
    alteration_flags: list[str] | None = None,
) -> FraudResult:
    ft = policy.fraud_thresholds
    same_day_limit = int(ft.get("same_day_claims_limit", 10**9))
    monthly_limit = int(ft.get("monthly_claims_limit", 10**9))
    auto_review_above = int(ft.get("auto_manual_review_above", 10**9))
    score_threshold = float(ft.get("fraud_score_manual_review_threshold", 1.0))

    res = FraudResult()
    score = 0.0

    # same-day velocity (history + current)
    same_day = sum(1 for h in claim.claims_history if h.date == claim.treatment_date) + 1
    if same_day > same_day_limit:
        res.signals.append(
            FraudSignal(
                type=FraudSignalType.SAME_DAY_CLAIMS,
                detail=f"{same_day} claims on {claim.treatment_date} exceeds the same-day limit of {same_day_limit}.",
                data={"count": same_day, "limit": same_day_limit, "date": claim.treatment_date},
            )
        )
        score += _WEIGHTS[FraudSignalType.SAME_DAY_CLAIMS]
        res.trace.append(
            ev(
                "fraud.same_day",
                TraceStatus.FAIL,
                f"Same-day claim count {same_day} > limit {same_day_limit}.",
                policy_ref="fraud_thresholds.same_day_claims_limit",
                count=same_day,
                limit=same_day_limit,
            )
        )

    # monthly velocity
    month = claim.treatment_date[:7]
    monthly = sum(1 for h in claim.claims_history if h.date and h.date[:7] == month) + 1
    if monthly > monthly_limit:
        res.signals.append(
            FraudSignal(
                type=FraudSignalType.MONTHLY_CLAIMS_EXCEEDED,
                detail=f"{monthly} claims in {month} exceeds the monthly limit of {monthly_limit}.",
                data={"count": monthly, "limit": monthly_limit, "month": month},
            )
        )
        score += _WEIGHTS[FraudSignalType.MONTHLY_CLAIMS_EXCEEDED]
        res.trace.append(
            ev(
                "fraud.monthly",
                TraceStatus.FAIL,
                f"Monthly claim count {monthly} > limit {monthly_limit}.",
                policy_ref="fraud_thresholds.monthly_claims_limit",
            )
        )

    # high-value auto review
    if claim.claimed_amount > auto_review_above:
        res.signals.append(
            FraudSignal(
                type=FraudSignalType.HIGH_VALUE_CLAIM,
                detail=f"Claimed amount {claim.claimed_amount} exceeds the auto-review threshold {auto_review_above}.",
                data={"claimed": claim.claimed_amount, "threshold": auto_review_above},
            )
        )
        score += _WEIGHTS[FraudSignalType.HIGH_VALUE_CLAIM]
        res.trace.append(
            ev(
                "fraud.high_value",
                TraceStatus.FAIL,
                f"Claim {claim.claimed_amount} > auto-review threshold {auto_review_above}.",
                policy_ref="fraud_thresholds.auto_manual_review_above",
            )
        )

    # document alteration (from extraction signals)
    for flag in alteration_flags or []:
        res.signals.append(
            FraudSignal(
                type=FraudSignalType.DOCUMENT_ALTERATION,
                detail=flag,
                data={"flag": flag},
            )
        )
        score += _WEIGHTS[FraudSignalType.DOCUMENT_ALTERATION]

    res.score = round(score, 2)
    res.manual_review = bool(res.signals) or res.score >= score_threshold
    if not res.signals:
        res.trace.append(
            ev(
                "fraud.scan",
                TraceStatus.PASS,
                "No fraud or anomaly signals detected.",
                policy_ref="fraud_thresholds",
                score=res.score,
            )
        )
    return res
