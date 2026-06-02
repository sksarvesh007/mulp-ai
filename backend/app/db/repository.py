"""DB-backed claim store. Persists every processed claim so past claims survive
restarts and power the ops history view. Swappable backend via ``settings.db_url``."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import String, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.sql.sqltypes import AutoString

from app.core.config import get_settings
from app.db.models import ClaimRecord
from app.observability.logs import get_logger
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimResult

log = get_logger("app.store")


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


@lru_cache
def get_store() -> ClaimRepository:
    return ClaimRepository(get_settings().db_url)


# Backwards-compatible module-level handle used by the API routes.
store = get_store()
