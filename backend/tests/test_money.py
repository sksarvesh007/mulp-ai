from __future__ import annotations

import pytest

from app.core.money import apply_percent, deduct_percent, fmt_inr


@pytest.mark.parametrize(
    "amount,pct,expected",
    [(1500, 10, 150), (4500, 20, 900), (3600, 10, 360), (0, 10, 0), (100, 0, 0), (101, 50, 51)],
)
def test_apply_percent(amount: int, pct: float, expected: int) -> None:
    assert apply_percent(amount, pct) == expected


def test_deduct_percent() -> None:
    assert deduct_percent(1500, 10) == 1350
    assert deduct_percent(4500, 20) == 3600
    assert deduct_percent(1000, 0) == 1000


def test_round_half_up() -> None:
    # 12.5 -> 13 (half up), not 12 (banker's)
    assert apply_percent(125, 10) == 13


def test_fmt_inr() -> None:
    assert fmt_inr(1350) == "₹1,350"
    assert fmt_inr(None) == "—"
    assert fmt_inr(1000000) == "₹1,000,000"
    assert fmt_inr(99.6) == "₹100"
