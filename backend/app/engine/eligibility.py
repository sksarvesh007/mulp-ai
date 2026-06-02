"""Stages 3-5 — member/policy validity, submission compliance, and eligibility
hard-rejects (category cover, exclusions, waiting period, pre-authorization).

Eligibility hard-rejects beat financial limits. Exclusion is checked BEFORE the
waiting period so an outright-excluded condition (obesity) yields EXCLUDED_CONDITION,
never WAITING_PERIOD (PLAN.md §4.1 #3). The first failing check terminates.
"""

from __future__ import annotations

from app.core.clock import add_days, parse_date
from app.core.money import fmt_inr
from app.engine.conditions import map_waiting_condition, match_exclusion
from app.engine.results import EligibilityResult
from app.engine.trace_util import ev
from app.engine.view import ClaimView
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from app.schemas.enums import RejectionReason, TraceStatus

# Tests that require pre-authorization are read from the policy; matched as substrings.


def evaluate_eligibility(
    claim: ClaimInput,
    view: ClaimView,
    policy: PolicyRepository,
) -> EligibilityResult:
    category = claim.claim_category.value
    res = EligibilityResult()

    def reject(reason: RejectionReason, headline: str, eligible_from: str | None = None) -> EligibilityResult:
        res.hard_reject = True
        res.reasons = [reason.value]
        res.headline = headline
        res.eligible_from = eligible_from
        return res

    # ── Stage 3: member / policy validity ─────────────────────────────────────
    member = policy.member(claim.member_id)
    if member is None:
        res.member_valid = False
        res.trace.append(
            ev(
                "eligibility.member",
                TraceStatus.FAIL,
                f"Member {claim.member_id} not found on policy.",
            )
        )
        return reject(
            RejectionReason.MEMBER_INVALID,
            f"Member {claim.member_id} is not on policy {claim.policy_id}.",
        )
    if claim.policy_id != policy.policy_id:
        res.trace.append(ev("eligibility.policy", TraceStatus.FAIL, "Claim policy id does not match the policy."))
        return reject(
            RejectionReason.MEMBER_INVALID,
            f"Policy {claim.policy_id} does not match member's policy.",
        )
    if policy.policy_holder.get("renewal_status") != "ACTIVE":
        res.trace.append(ev("eligibility.policy", TraceStatus.FAIL, "Policy is not ACTIVE."))
        return reject(RejectionReason.POLICY_INACTIVE, "The policy is not active.")
    res.trace.append(
        ev(
            "eligibility.member",
            TraceStatus.PASS,
            f"Member {member['name']} ({claim.member_id}) is valid and active.",
            policy_ref="members",
        )
    )

    # ── Stage 3b: treatment date within the policy coverage window ────────────
    # A treatment that pre-dates the policy or lies beyond its end (incl. an
    # impossible future date) can't be claimed — the policy wasn't in force then.
    holder = policy.policy_holder
    coverage_start = parse_date(holder["policy_start_date"])
    coverage_end = parse_date(holder["policy_end_date"])
    treat_date = parse_date(claim.treatment_date)
    if not (coverage_start <= treat_date <= coverage_end):
        res.trace.append(
            ev(
                "eligibility.coverage_period",
                TraceStatus.FAIL,
                f"Treatment on {claim.treatment_date} is outside the policy coverage period "
                f"({holder['policy_start_date']} to {holder['policy_end_date']}).",
                policy_ref="policy_holder.policy_start_date",
            )
        )
        return reject(
            RejectionReason.TREATMENT_DATE_INVALID,
            f"Treatment date {claim.treatment_date} is outside the policy coverage period "
            f"({holder['policy_start_date']} to {holder['policy_end_date']}); the policy was not "
            f"in force on that date.",
        )
    res.trace.append(
        ev(
            "eligibility.coverage_period",
            TraceStatus.PASS,
            f"Treatment on {claim.treatment_date} falls within the coverage period.",
            policy_ref="policy_holder.policy_start_date",
        )
    )

    # ── Stage 4: submission compliance ────────────────────────────────────────
    sub = policy.submission_rules
    min_amount = int(sub.get("minimum_claim_amount", 0))
    if claim.claimed_amount < min_amount:
        res.trace.append(
            ev(
                "eligibility.min_amount",
                TraceStatus.FAIL,
                f"Claimed {fmt_inr(claim.claimed_amount)} is below the minimum {fmt_inr(min_amount)}.",
                policy_ref="submission_rules.minimum_claim_amount",
            )
        )
        return reject(
            RejectionReason.BELOW_MINIMUM_AMOUNT,
            f"Claimed amount {fmt_inr(claim.claimed_amount)} is below the minimum claimable "
            f"amount of {fmt_inr(min_amount)}.",
        )

    deadline_days = int(sub.get("deadline_days_from_treatment", 0))
    if claim.submission_date:
        days = (parse_date(claim.submission_date) - parse_date(claim.treatment_date)).days
        if days > deadline_days:
            res.trace.append(
                ev(
                    "eligibility.deadline",
                    TraceStatus.FAIL,
                    f"Submitted {days} days after treatment; limit is {deadline_days} days.",
                    policy_ref="submission_rules.deadline_days_from_treatment",
                )
            )
            return reject(
                RejectionReason.SUBMISSION_DEADLINE_EXCEEDED,
                f"Claim submitted {days} days after treatment, exceeding the {deadline_days}-day window.",
            )
        res.trace.append(
            ev(
                "eligibility.deadline",
                TraceStatus.PASS,
                f"Submitted within the {deadline_days}-day window.",
            )
        )
    else:
        res.trace.append(
            ev(
                "eligibility.deadline",
                TraceStatus.SKIP,
                "No submission date supplied — treated as within window (documented assumption).",
            )
        )

    # ── Stage 5a: category covered ────────────────────────────────────────────
    cat = policy.category_optional(category)
    if not cat or not cat.get("covered", False):
        res.category_covered = False
        res.trace.append(
            ev(
                "eligibility.category",
                TraceStatus.FAIL,
                f"Category {category} is not covered.",
                policy_ref=f"opd_categories.{category.lower()}.covered",
            )
        )
        return reject(
            RejectionReason.CATEGORY_NOT_COVERED,
            f"Treatment category {category} is not covered under this policy.",
        )
    res.trace.append(
        ev(
            "eligibility.category",
            TraceStatus.PASS,
            f"Category {category} is covered.",
            policy_ref=f"opd_categories.{category.lower()}.covered",
        )
    )

    # ── Stage 5c: exclusions (checked BEFORE waiting — exclusion wins) ─────────
    excluded = match_exclusion(view.condition_text, policy)
    if excluded:
        res.trace.append(
            ev(
                "eligibility.exclusion",
                TraceStatus.FAIL,
                f"Diagnosis/treatment matches an excluded condition: '{excluded}'.",
                policy_ref="exclusions.conditions",
                matched=excluded,
                text=view.condition_text,
            )
        )
        return reject(
            RejectionReason.EXCLUDED_CONDITION,
            f"This claim is for '{excluded}', which is explicitly excluded under the policy and is not payable.",
        )
    res.trace.append(
        ev(
            "eligibility.exclusion",
            TraceStatus.PASS,
            "No excluded condition matched.",
            policy_ref="exclusions.conditions",
        )
    )

    # ── Stage 5b: waiting period ──────────────────────────────────────────────
    join = parse_date(member["join_date"])
    treatment = parse_date(claim.treatment_date)
    cond = map_waiting_condition(view.condition_text, policy)
    if cond:
        key, days = cond
        eligible = add_days(join, days)
        if treatment < eligible:
            res.trace.append(
                ev(
                    "eligibility.waiting_period",
                    TraceStatus.FAIL,
                    f"{key.replace('_', ' ')} has a {days}-day waiting period; eligible from {eligible.isoformat()}.",
                    policy_ref=f"waiting_periods.specific_conditions.{key}",
                    condition=key,
                    waiting_days=days,
                    join_date=member["join_date"],
                    treatment_date=claim.treatment_date,
                    eligible_from=eligible.isoformat(),
                )
            )
            return reject(
                RejectionReason.WAITING_PERIOD,
                f"Claims for {key.replace('_', ' ')} have a {days}-day waiting period from the join date "
                f"({member['join_date']}). The member is eligible for {key.replace('_', ' ')}-related claims "
                f"from {eligible.isoformat()}; treatment on {claim.treatment_date} falls within the waiting period.",
                eligible_from=eligible.isoformat(),
            )
        res.trace.append(
            ev(
                "eligibility.waiting_period",
                TraceStatus.PASS,
                f"Past the {days}-day waiting period for {key.replace('_', ' ')} (eligible {eligible.isoformat()}).",
                policy_ref=f"waiting_periods.specific_conditions.{key}",
            )
        )
    else:
        initial = int(policy.waiting_periods.get("initial_waiting_period_days", 0))
        eligible = add_days(join, initial)
        if treatment < eligible:
            res.trace.append(
                ev(
                    "eligibility.waiting_period",
                    TraceStatus.FAIL,
                    f"Within the {initial}-day initial waiting period; eligible from {eligible.isoformat()}.",
                    policy_ref="waiting_periods.initial_waiting_period_days",
                    eligible_from=eligible.isoformat(),
                )
            )
            return reject(
                RejectionReason.WAITING_PERIOD,
                f"The {initial}-day initial waiting period applies; the member is eligible "
                f"from {eligible.isoformat()}.",
                eligible_from=eligible.isoformat(),
            )
        res.trace.append(
            ev(
                "eligibility.waiting_period",
                TraceStatus.PASS,
                f"Past the {initial}-day initial waiting period.",
                policy_ref="waiting_periods.initial_waiting_period_days",
            )
        )

    # ── Stage 5d: pre-authorization ───────────────────────────────────────────
    diag = policy.category_optional("diagnostic") or {}
    high_value_tests: list[str] = diag.get("high_value_tests_requiring_pre_auth", [])
    threshold = int(diag.get("pre_auth_threshold", 0))
    candidates = [
        *view.tests,
        *[li.description for li in view.line_items],
        view.treatment_text,
        view.diagnosis_text,
    ]
    for test in high_value_tests:
        if any(test.lower() in (c or "").lower() for c in candidates):
            amount = next(
                (li.amount for li in view.line_items if test.lower() in li.description.lower()),
                claim.claimed_amount,
            )
            requires = ("pet" in test.lower()) or (amount > threshold)
            if requires and not claim.pre_auth_reference:
                res.trace.append(
                    ev(
                        "eligibility.pre_auth",
                        TraceStatus.FAIL,
                        f"{test} ({fmt_inr(amount)}) requires pre-authorization "
                        f"(threshold {fmt_inr(threshold)}); none supplied.",
                        policy_ref="opd_categories.diagnostic.high_value_tests_requiring_pre_auth",
                        test=test,
                        amount=amount,
                        threshold=threshold,
                    )
                )
                validity = int(policy.pre_authorization.get("validity_days", 30))
                return reject(
                    RejectionReason.PRE_AUTH_MISSING,
                    f"Pre-authorization was required for {test} ({fmt_inr(amount)} exceeds the "
                    f"{fmt_inr(threshold)} threshold) but was not obtained. Please obtain pre-authorization "
                    f"from the insurer and resubmit the claim within {validity} days of approval.",
                )
    res.trace.append(
        ev(
            "eligibility.pre_auth",
            TraceStatus.PASS,
            "No pre-authorization requirement triggered.",
            policy_ref="pre_authorization",
        )
    )

    return res
