from datetime import datetime, timezone
import json
import logging

from tools.health_schema import SymptomLog, Severity
from memory.index import upsert_entries
from db.engine import SessionLocal, Base, engine
from db.models import SymptomLogORM


def ensure_tables() -> None:
    """Create database tables if they do not already exist."""
    Base.metadata.create_all(engine)


logger = logging.getLogger(__name__)


def tool_log(text: str, user_id: str) -> str:
    """Persist a free-form symptom description.

    Parameters
    ----------
    text : str
        Description provided by the user.
    user_id : str
        Identifier for the submitting user.
    """
    ensure_tables()

    entry = SymptomLog(
        symptom=text,
        severity=Severity.none,
        started_at=datetime.now(timezone.utc),
        notes=json.dumps({"user_id": user_id}),
    )

    with SessionLocal() as db:
        try:
            orm_entry = SymptomLogORM(**entry.model_dump())
            db.add(orm_entry)
            db.commit()
            db.refresh(orm_entry)

            upsert_entries(
                user_id,
                [SymptomLog.model_validate(orm_entry, from_attributes=True)],
            )
        except Exception as exc:
            db.rollback()
            logger.error("Failed to log symptom entry: %s", exc)
            raise

    return f"Logged entry with id: {orm_entry.id}"


def log_entry(user_id: str, message: str) -> str:
    """Convenience wrapper matching the adapter signature used by the API layer."""

    return tool_log(text=message, user_id=user_id)
