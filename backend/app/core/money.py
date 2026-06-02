"""Money helpers. Canonical money type is **integer rupees** (all policy + claim
amounts in this domain are whole rupees). Percentage operations round half-up to
the nearest rupee so results are deterministic and reproducible across the eval."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def apply_percent(amount: int, percent: float) -> int:
    """Return ``percent`` % of ``amount`` as whole rupees (round half-up).

    >>> apply_percent(1500, 10)
    150
    >>> apply_percent(4500, 20)
    900
    """
    value = Decimal(amount) * Decimal(str(percent)) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def deduct_percent(amount: int, percent: float) -> int:
    """Return ``amount`` minus ``percent`` % of it, as whole rupees."""
    return amount - apply_percent(amount, percent)


def fmt_inr(amount: int | float | None) -> str:
    """Format an amount as an INR string for member/ops-facing messages."""
    if amount is None:
        return "—"
    return f"₹{int(round(amount)):,}"
