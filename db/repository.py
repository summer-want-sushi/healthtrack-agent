"""
Thin CRUD wrapper around SQLAlchemy sessions.
"""
from contextlib import contextmanager
from typing import Iterable, List

from db.engine import SessionLocal
from db.models import SymptomLogORM
from tools.health_schema import SymptomLog

@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# ---------- CRUD -----------------------------------------------------

def add_log(log: SymptomLog) -> None:
    """Persist a ``SymptomLog`` instance."""
    with session_scope() as db:
        db.add(SymptomLogORM(**log.model_dump()))

def list_logs() -> List[SymptomLog]:
    with session_scope() as db:
        rows: Iterable[SymptomLogORM] = db.query(SymptomLogORM).all()
        return [SymptomLog.model_validate(row, from_attributes=True) for row in rows]

def get_log(log_id: str) -> SymptomLog | None:
    with session_scope() as db:
        row = db.get(SymptomLogORM, log_id)
        return (
            SymptomLog.model_validate(row, from_attributes=True) if row else None
        )
