"""Stage 7 — Adjudication / financial engine. The ONLY place money is computed.
Fully deterministic so it is unit-testable and never hallucinates an amount.

Pinned interpretations (PLAN.md §4.1):
  #1 OPD category sub_limits are annual aggregates, NOT per-claim caps — the only
     single-claim ceiling for OPD is ``per_claim_limit``.
  #2 ``PER_CLAIM_EXCEEDED`` is a full REJECT for OPD categories
     (consultation/diagnostic/pharmacy); dental/vision/alt-medicine are bounded by
     their own sub_limit. So TC008 → REJECT and TC006 → PARTIAL ₹8000 both hold.
  #4 Network discount is applied BEFORE co-pay, always, and shown in that order.
"""

from __future__ import annotations

from app.core.money import apply_percent, deduct_percent, fmt_inr
from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult
from app.engine.trace_util import ev
from app.engine.view import ClaimView
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from app.schemas.decision import FinancialBreakdown, LineItemDecision
from app.schemas.enums import ClaimCategory, LineItemStatus, TraceStatus

# per_claim_limit applies as a hard reject only to these (OPD) categories.
_OPD_PERCLAIM = {
    ClaimCategory.CONSULTATION.value,
    ClaimCategory.DIAGNOSTIC.value,
    ClaimCategory.PHARMACY.value,
}
# these categories are bounded by their own sub_limit cap.
_SELF_SUBLIMIT = {
    ClaimCategory.DENTAL.value,
    ClaimCategory.VISION.value,
    ClaimCategory.ALTERNATIVE_MEDICINE.value,
}


def _matches_any(desc: str, items: list[str]) -> bool:
    low = desc.lower()
    return any(x.lower() in low or low in x.lower() for x in items)


def adjudicate(
    claim: ClaimInput,
    view: ClaimView,
    policy: PolicyRepository,
    eligibility: EligibilityResult,
    fraud: FraudResult,
) -> AdjudicationResult:
    # earlier stages already resolved the claim → don't compute money
    if eligibility.hard_reject or fraud.manual_review:
        return AdjudicationResult(
            skipped=True,
            trace=[
                ev(
                    "adjudication",
                    TraceStatus.SKIP,
                    "Skipped — claim resolved at an earlier stage.",
                )
            ],
        )

    category = claim.claim_category.value
    cat = policy.category(category)
    copay_percent = float(cat.get("copay_percent", 0))
    network_discount_percent = float(cat.get("network_discount_percent", 0))
    sub_limit = cat.get("sub_limit")
    claimed = claim.claimed_amount

    res = AdjudicationResult(claimed_total=claimed)

    # ── 7a. Line-item classification (only categories with covered/excluded lists) ─
    covered_list = cat.get("covered_procedures") or cat.get("covered_items")
    excluded_list = cat.get("excluded_procedures") or cat.get("excluded_items")
    has_lists = bool(covered_list or excluded_list)

    if has_lists and view.line_items:
        covered_subtotal = 0
        for li in view.line_items:
            if excluded_list and _matches_any(li.description, excluded_list):
                res.has_excluded = True
                res.line_items.append(
                    LineItemDecision(
                        description=li.description,
                        amount=li.amount,
                        status=LineItemStatus.EXCLUDED,
                        approved_amount=0,
                        reason=f"'{li.description}' is an excluded/cosmetic procedure not covered under {category}.",
                    )
                )
            else:
                covered_subtotal += li.amount
                res.line_items.append(
                    LineItemDecision(
                        description=li.description,
                        amount=li.amount,
                        status=LineItemStatus.COVERED,
                        approved_amount=li.amount,
                    )
                )
        base = covered_subtotal
        res.trace.append(
            ev(
                "adjudication.line_items",
                TraceStatus.PASS,
                f"Covered subtotal {fmt_inr(base)} from {len(view.line_items)} line item(s); "
                f"{sum(1 for li in res.line_items if li.status == LineItemStatus.EXCLUDED)} excluded.",
                policy_ref=f"opd_categories.{category.lower()}",
            )
        )
    else:
        base = claimed
        for li in view.line_items:
            res.line_items.append(
                LineItemDecision(
                    description=li.description,
                    amount=li.amount,
                    status=LineItemStatus.COVERED,
                    approved_amount=li.amount,
                )
            )

    # ── 7b. Per-claim limit (full reject for OPD categories) ──────────────────
    per_claim_limit = policy.per_claim_limit
    if category in _OPD_PERCLAIM and not res.has_excluded and claimed > per_claim_limit:
        res.per_claim_exceeded = True
        res.approved_amount = 0
        res.headline = (
            f"The claimed amount {fmt_inr(claimed)} exceeds the per-claim limit of "
            f"{fmt_inr(per_claim_limit)}. The entire claim is rejected."
        )
        res.trace.append(
            ev(
                "adjudication.per_claim",
                TraceStatus.FAIL,
                f"Claimed {fmt_inr(claimed)} > per-claim limit {fmt_inr(per_claim_limit)} → full reject.",
                policy_ref="coverage.per_claim_limit",
                claimed=claimed,
                limit=per_claim_limit,
            )
        )
        return res

    # ── 7c. Network discount THEN co-pay (order is fixed) ─────────────────────
    is_network = policy.is_network_hospital(claim.hospital_name or view.hospital_name)
    after_discount = deduct_percent(base, network_discount_percent) if is_network else base
    network_discount = base - after_discount
    copay = apply_percent(after_discount, copay_percent)
    after_copay = after_discount - copay
    payable = after_copay

    if is_network and network_discount:
        res.trace.append(
            ev(
                "adjudication.network_discount",
                TraceStatus.PASS,
                f"Network hospital: {network_discount_percent:.0f}% discount "
                f"({fmt_inr(base)} → {fmt_inr(after_discount)}).",
                policy_ref=f"opd_categories.{category.lower()}.network_discount_percent",
            )
        )
    if copay:
        res.trace.append(
            ev(
                "adjudication.copay",
                TraceStatus.PASS,
                f"{copay_percent:.0f}% co-pay applied: {fmt_inr(copay)} deducted "
                f"({fmt_inr(after_discount)} → {fmt_inr(after_copay)}).",
                policy_ref=f"opd_categories.{category.lower()}.copay_percent",
            )
        )

    # ── 7d. Caps: own sub-limit (dental/vision/alt-med) + annual OPD ──────────
    clamps: list[str] = []
    if category in _SELF_SUBLIMIT and sub_limit is not None and payable > int(sub_limit):
        clamps.append(f"Capped at {category} sub-limit {fmt_inr(int(sub_limit))}.")
        res.trace.append(
            ev(
                "adjudication.sub_limit",
                TraceStatus.PASS,
                f"Payable capped at {category} sub-limit {fmt_inr(int(sub_limit))}.",
                policy_ref=f"opd_categories.{category.lower()}.sub_limit",
            )
        )
        payable = int(sub_limit)

    remaining_opd = policy.annual_opd_limit - claim.ytd_claims_amount
    if payable > max(0, remaining_opd):
        clamps.append(f"Capped at remaining annual OPD limit {fmt_inr(max(0, remaining_opd))}.")
        res.trace.append(
            ev(
                "adjudication.annual_opd",
                TraceStatus.PASS,
                f"Payable capped at remaining annual OPD limit {fmt_inr(max(0, remaining_opd))}.",
                policy_ref="coverage.annual_opd_limit",
            )
        )
        payable = max(0, remaining_opd)

    # Hard invariant: never approve more than the member requested.
    if payable > claimed:
        clamps.append(f"Capped at the claimed amount {fmt_inr(claimed)} (never approve more than requested).")
        res.trace.append(
            ev(
                "adjudication.claimed_cap",
                TraceStatus.PASS,
                f"Payable capped at the claimed amount {fmt_inr(claimed)}.",
            )
        )
        payable = claimed

    res.approved_amount = payable
    res.payable = payable
    res.breakdown = FinancialBreakdown(
        base=base,
        is_network=is_network,
        network_discount=network_discount,
        after_discount=after_discount,
        copay=copay,
        after_copay=after_copay,
        clamps=clamps,
        final=payable,
    )

    if res.has_excluded and payable > 0:
        res.headline = f"Partially approved {fmt_inr(payable)}; excluded line items removed."
    elif is_network:
        res.headline = (
            f"Approved {fmt_inr(payable)} ({network_discount_percent:.0f}% network discount "
            f"then {copay_percent:.0f}% co-pay)."
        )
    elif copay:
        res.headline = f"Approved {fmt_inr(payable)} after {copay_percent:.0f}% co-pay ({fmt_inr(copay)} deducted)."
    else:
        res.headline = f"Approved {fmt_inr(payable)}."

    return res
