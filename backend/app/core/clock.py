"""Time helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_date(value: str) -> date:
    """Parse an ISO date (YYYY-MM-DD)."""
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)
