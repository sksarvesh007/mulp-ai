"""Supabase-backed claims ledger (PostgREST over httpx).

Records every LIVE claim submission with its dates, and looks up a member's prior
submissions, so the history-dependent fraud rules in ``app/engine/fraud.py`` (same-day
and monthly velocity) work across *real* submissions — not only when a ``claims_history``
is hand-supplied on the input. The fraud engine already counts velocity from
``claim.claims_history`` (+ the current claim), so we simply populate that list from the
ledger before the graph runs, then persist the claim afterwards.

Best-effort by design: any network/DB error is swallowed so a claim decision is NEVER
blocked by persistence. Active only in LIVE mode when a Supabase URL + key are configured;
in eval mode (the deterministic 12-case harness) it is a no-op, so determinism is intact.

Contract
--------
load_member_history(claim) : (LIVE + configured) extend claim.claims_history with the
                             member's prior ledger rows; no-op otherwise. Never raises.
record_claim(claim, result): (LIVE + configured) insert/upsert one row for this submission
                             (created_at is set server-side); no-op otherwise. Never raises.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.observability.logs import get_logger
from app.schemas.claim import ClaimHistoryItem, ClaimInput
from app.schemas.decision import ClaimResult
from app.schemas.enums import ExtractionMode

log = get_logger("app.ledger")

_TIMEOUT = 8.0


def _endpoint() -> tuple[str, dict[str, str]] | None:
    """Return (table_url, headers) for the configured Supabase REST table, or None."""
    s = get_settings()
    if not s.claims_ledger_enabled:
        return None
    base = f"{s.supabase_url.rstrip('/')}/rest/v1/{s.supabase_claims_table}"
    headers = {
        "apikey": s.supabase_key,
        "Authorization": f"Bearer {s.supabase_key}",
        "Content-Type": "application/json",
    }
    return base, headers


async def load_member_history(claim: ClaimInput) -> None:  # pragma: no cover - network I/O
    """Populate ``claim.claims_history`` from the ledger so the fraud node sees the
    member's prior submissions. No-op outside LIVE mode or when Supabase isn't configured."""
    if claim.mode != ExtractionMode.LIVE:
        return
    ep = _endpoint()
    if ep is None:
        return
    base, headers = ep
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                base,
                params={
                    "member_id": f"eq.{claim.member_id}",
                    "select": "claim_id,treatment_date,claimed_amount",
                },
                headers=headers,
            )
            resp.raise_for_status()
            rows = resp.json()
        prior = [
            ClaimHistoryItem(
                claim_id=row.get("claim_id"),
                date=row.get("treatment_date"),
                amount=row.get("claimed_amount"),
            )
            for row in rows
            if row.get("claim_id") != claim.claim_id  # never count the current claim against itself
        ]
        if prior:
            claim.claims_history = [*claim.claims_history, *prior]
        log.info("ledger.history_loaded", member_id=claim.member_id, prior_claims=len(prior))
    except Exception as exc:
        # best-effort: a ledger hiccup must never block a decision — but log it, don't hide it
        log.warning("ledger.history_failed", member_id=claim.member_id, error=str(exc), error_type=type(exc).__name__)
        return


async def record_claim(claim: ClaimInput, result: ClaimResult) -> None:  # pragma: no cover - network I/O
    """Persist this processed LIVE submission (its treatment date is stored; ``created_at``
    is set server-side). Upserts by ``claim_id``. No-op outside LIVE mode or when unconfigured."""
    if claim.mode != ExtractionMode.LIVE:
        return
    ep = _endpoint()
    if ep is None:
        return
    base, headers = ep
    d = result.decision
    row = {
        "claim_id": result.claim_id,
        "member_id": claim.member_id,
        "policy_id": claim.policy_id,
        "claim_category": claim.claim_category.value,
        "treatment_date": claim.treatment_date,
        "claimed_amount": claim.claimed_amount,
        "decision": d.decision.value if d.decision else None,
        "status": d.status.value if d.status else None,
        "approved_amount": d.approved_amount,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                base,
                params={"on_conflict": "claim_id"},  # upsert by claim_id (idempotent on retry)
                json=row,
                headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            resp.raise_for_status()
        log.info("ledger.recorded", claim_id=result.claim_id, status_code=resp.status_code)
    except Exception as exc:
        # best-effort: persistence failure must never break the response — but log it
        log.warning("ledger.record_failed", claim_id=result.claim_id, error=str(exc), error_type=type(exc).__name__)
        return


async def seed_history(member_id: str, treatment_date: str, count: int) -> int:  # pragma: no cover - network I/O
    """Insert ``count`` synthetic prior claims for a member on a date, so the same-day velocity
    demo example trips on the next real submission. Idempotent (upsert by claim_id). Returns the
    number requested, or 0 if Supabase isn't configured / the write failed."""
    ep = _endpoint()
    if ep is None:
        return 0
    base, headers = ep
    rows = [
        {
            "claim_id": f"SEED_{member_id}_{treatment_date}_{i}",
            "member_id": member_id,
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": treatment_date,
            "claimed_amount": 1500,
            "decision": "APPROVED",
            "status": "DECIDED",
            "approved_amount": 1350,
        }
        for i in range(max(0, count))
    ]
    if not rows:
        return 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                base,
                params={"on_conflict": "claim_id"},
                json=rows,
                headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            resp.raise_for_status()
        log.info("ledger.seeded", member_id=member_id, rows=len(rows))
        return len(rows)
    except Exception as exc:
        log.warning("ledger.seed_failed", member_id=member_id, error=str(exc), error_type=type(exc).__name__)
        return 0
