"""Time helpers. Wall-clock timestamps are emitted in IST (Asia/Kolkata, UTC+5:30) — the
operating timezone for this Indian health-insurance product — so traces, logs and analytics
all read in local time. (DB ``created_at`` is still stored in UTC, the correct storage tz;
it is converted to IST only for display/grouping via ``to_ist``.)"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_iso() -> str:
    """Current time as an ISO-8601 string in IST (e.g. ``2026-06-03T14:05:00+05:30``)."""
    return datetime.now(IST).isoformat()


def to_ist(dt: datetime) -> datetime:
    """Convert any datetime to IST; a naive datetime is assumed to be UTC (our storage tz)."""
    return (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).astimezone(IST)


def parse_date(value: str) -> date:
    """Parse an ISO date (YYYY-MM-DD)."""
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)
