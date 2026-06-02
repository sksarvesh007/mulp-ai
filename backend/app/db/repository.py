"""DB-backed claim store. Persists every processed claim so past claims survive
restarts and power the ops history view. Swappable backend via ``settings.db_url``."""

from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from sqlalchemy import String, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.sql.sqltypes import AutoString

from app.core.clock import to_ist
from app.core.config import get_settings
from app.db.models import ClaimRecord
from app.observability.logs import get_logger
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimResult

log = get_logger("app.store")

# A claim's decision/status collapses to one of five display segments for the dashboard.
_DECISION_SEGMENT = {"APPROVED": "approved", "PARTIAL": "partial", "REJECTED": "rejected", "MANUAL_REVIEW": "review"}
_CONFIDENCE_BUCKETS = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]


def _segment(decision: str | None, status: str) -> str:
    """Map a (decision, status) pair onto exactly one dashboard segment."""
    if decision in _DECISION_SEGMENT:
        return _DECISION_SEGMENT[decision]
    return "review" if status == "PENDING_REVIEW" else "action"  # None decision: awaiting human / member


class ClaimRepository:
    def __init__(self, db_url: str) -> None:
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        self.engine = create_engine(db_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """Add any model columns missing from an existing table (additive only).

        ``create_all`` never alters an existing table, so a DB created before a new
        column was added would be missing it. This brings the schema forward without
        dropping data — enough for SQLite; a real deployment would use Alembic.
        """
        table = ClaimRecord.__tablename__
        existing = {c["name"] for c in inspect(self.engine).get_columns(table)}
        with self.engine.begin() as conn:
            for col in ClaimRecord.__table__.columns:  # type: ignore[attr-defined]
                if col.name in existing:
                    continue
                ddl_type = col.type.compile(self.engine.dialect)
                # SQLModel maps `str` to AutoString (a TypeDecorator, not a String subclass),
                # so check both: text columns backfill existing rows with '', others with NULL.
                default = "''" if isinstance(col.type, (String, AutoString)) else "NULL"
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col.name}" {ddl_type} DEFAULT {default}'))

    def put(
        self,
        result: ClaimResult,
        *,
        member_id: str = "",
        category: str = "",
        claim: ClaimInput | None = None,
    ) -> None:
        d = result.decision
        record = ClaimRecord(
            claim_id=result.claim_id,
            member_id=member_id,
            category=category,
            decision=d.decision.value if d.decision else None,
            status=d.status.value,
            approved_amount=d.approved_amount,
            confidence=d.confidence,
            degraded=d.degraded,
            result_json=result.model_dump_json(),
            input_json=claim.model_dump_json() if claim is not None else "",
        )
        with Session(self.engine) as session:
            session.merge(record)  # upsert by claim_id
            session.commit()
        log.debug(
            "store.put",
            claim_id=result.claim_id,
            status=record.status,
            decision=record.decision,
            approved_amount=record.approved_amount,
        )

    def get(self, claim_id: str) -> ClaimResult | None:
        with Session(self.engine) as session:
            record = session.get(ClaimRecord, claim_id)
            if record is None or not record.result_json:  # absent, or a pre-migration legacy row
                return None
            return ClaimResult.model_validate_json(record.result_json)

    def get_input(self, claim_id: str) -> ClaimInput | None:
        """The original ClaimInput, for replays and review→dataset items."""
        with Session(self.engine) as session:
            record = session.get(ClaimRecord, claim_id)
            if record is None or not record.input_json:
                return None
            return ClaimInput.model_validate_json(record.input_json)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            records = session.exec(select(ClaimRecord).order_by(ClaimRecord.created_at.desc())).all()  # type: ignore[attr-defined]
        return [
            {
                "claim_id": r.claim_id,
                "member_id": r.member_id,
                "category": r.category,
                "decision": r.decision,
                "status": r.status,
                "approved_amount": r.approved_amount,
                "confidence": r.confidence,
                "degraded": r.degraded,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]


    def analytics(self) -> dict[str, Any]:
        """Aggregate every persisted claim into the dashboard payload (counts, money,
        per-category mix, a daily time series and a confidence histogram). Time grouping is
        by IST calendar day. Pure read; safe on any SQL backend."""
        with Session(self.engine) as session:
            records = session.exec(select(ClaimRecord)).all()

        seg_counts: Counter[str] = Counter()
        by_cat: dict[str, Counter[str]] = defaultdict(Counter)
        by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"claims": 0, "approved_amount": 0})
        conf_buckets = [0, 0, 0, 0, 0]
        confidences: list[float] = []
        total_approved = 0
        degraded = 0

        for r in records:
            seg = _segment(r.decision, r.status)
            seg_counts[seg] += 1
            cat = r.category or "UNKNOWN"
            by_cat[cat][seg] += 1
            by_cat[cat]["total"] += 1
            total_approved += r.approved_amount or 0
            if r.degraded:
                degraded += 1
            if r.confidence is not None:
                confidences.append(r.confidence)
                idx = min(4, max(0, int(r.confidence * 5)))  # 0.0–1.0 → bucket 0–4 (1.0 → top bucket)
                conf_buckets[idx] += 1
            if r.created_at is not None:
                day = to_ist(r.created_at).date().isoformat()
                by_day[day]["claims"] += 1
                by_day[day]["approved_amount"] += r.approved_amount or 0

        approved, partial, rejected = seg_counts["approved"], seg_counts["partial"], seg_counts["rejected"]
        rate_denom = approved + partial + rejected
        segments = ("approved", "partial", "rejected", "review", "action")
        labels = [("approved", "Approved"), ("partial", "Partial"), ("rejected", "Rejected"),
                  ("review", "In review"), ("action", "Action needed")]
        return {
            "total_claims": len(records),
            "approved": approved,
            "partial": partial,
            "rejected": rejected,
            "review": seg_counts["review"],
            "action": seg_counts["action"],
            "approval_rate": round((approved + partial) / rate_denom, 4) if rate_denom else 0.0,
            "total_approved_amount": total_approved,
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "degraded_count": degraded,
            "by_decision": [{"name": label, "value": seg_counts[key]} for key, label in labels if seg_counts[key]],
            "by_category": [
                {"category": cat, "total": c["total"], **{s: c[s] for s in segments}}
                for cat, c in sorted(by_cat.items(), key=lambda kv: -kv[1]["total"])
            ],
            "over_time": [{"date": d, **by_day[d]} for d in sorted(by_day)],
            "confidence_buckets": [{"bucket": b, "count": conf_buckets[i]} for i, b in enumerate(_CONFIDENCE_BUCKETS)],
        }


@lru_cache
def get_store() -> ClaimRepository:
    return ClaimRepository(get_settings().db_url)


# Backwards-compatible module-level handle used by the API routes.
store = get_store()
