from __future__ import annotations

from datetime import date

from app.core.clock import add_days, now_iso, parse_date


def test_parse_date() -> None:
    assert parse_date("2024-09-01") == date(2024, 9, 1)
    assert parse_date("2024-09-01T10:00:00") == date(2024, 9, 1)


def test_add_days() -> None:
    assert add_days(date(2024, 9, 1), 90) == date(2024, 11, 30)


def test_now_iso() -> None:
    s = now_iso()
    assert "T" in s and len(s) >= 19
