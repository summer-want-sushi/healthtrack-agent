"""
Thin CRUD wrapper around SQLAlchemy sessions.
"""
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.engine import SessionLocal as _DefaultSessionLocal, engine as _default_engine, Base
from db.models import SymptomLogORM
from tools.health_schema import SymptomLog

_engine_cwd = Path.cwd()
_engine = _default_engine
_SessionLocal = _DefaultSessionLocal

def init_db(engine) -> None:
    """Create database tables for a given engine."""
    from db import models  # noqa: F401 – ensure model import for metadata

    Base.metadata.create_all(engine)

@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations.

    If the current working directory changes, a new engine bound to the
    directory's ``health.db`` is created and initialized.
    """
    global _engine_cwd, _engine, _SessionLocal

    cwd = Path.cwd()
    if cwd != _engine_cwd:
        db_path = cwd / "health.db"
        url = f"sqlite:///{db_path}"
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        _engine_cwd = cwd
        init_db(_engine)

    db = _SessionLocal()
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
