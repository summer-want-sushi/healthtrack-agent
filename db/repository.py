"""
Thin CRUD wrapper around SQLAlchemy sessions.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.engine import SessionLocal as _DefaultSessionLocal, engine as _default_engine, Base
from db.models import SymptomLogORM
from tools.health_schema import SymptomLog

_engine_cwd = Path.cwd()
_engine = _default_engine
_SessionLocal = _DefaultSessionLocal
_engine_path = Path(_engine.url.database).resolve()

def init_db(engine) -> None:
    """
    Ensure all ORM models are imported and create database tables on the provided SQLAlchemy engine.
    
    This function imports the application's model modules to ensure the metadata is populated, then calls Base.metadata.create_all using the given engine to create any missing tables.
    
    Parameters:
        engine: A SQLAlchemy Engine or engine-like object to which the metadata will be bound for table creation.
    """
    from db import models  # noqa: F401 – ensure model import for metadata

    Base.metadata.create_all(engine)

@contextmanager
def session_scope():
    """
    Provide a transactional database session scoped to the current engine.
    
    If the HEALTH_DB_PATH environment variable or the current working directory changes, reinitializes the engine and session factory bound to the corresponding database file before yielding a session. The context commits the transaction on successful exit, rolls back and re-raises on exception, and always closes the session.
    
    Returns:
        db (Session): A SQLAlchemy Session bound to the active engine.
    """
    global _engine_cwd, _engine_path, _engine, _SessionLocal

    cwd = Path.cwd()
    env_path = os.environ.get("HEALTH_DB_PATH")
    if env_path:
        desired_path = Path(env_path).expanduser().resolve()
    else:
        desired_path = (cwd / "health.db").resolve()

    need_new_engine = desired_path != _engine_path or (env_path is None and cwd != _engine_cwd)

    if need_new_engine:
        url = f"sqlite:///{desired_path}"
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        _engine_cwd = cwd
        _engine_path = desired_path
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

def list_logs(
    user_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> List[SymptomLog]:
    """
    List logs with optional filters.

    Args:
        user_id: If provided, only return rows whose notes JSON has {"user_id": <user_id>}.
        since:   If provided, only return rows with created_at >= since.

    Note:
        We do not have a dedicated user_id column yet, so we read user_id
        from the notes JSON (if present). This preserves the behavior that
        existed in db/health_db.py::get_entries.
    """
    with session_scope() as db:
        q = db.query(SymptomLogORM)
        if since is not None:
            q = q.filter(SymptomLogORM.created_at >= since)

        rows: Iterable[SymptomLogORM] = q.all()
        results: List[SymptomLog] = []

        for row in rows:
            if user_id is not None:
                try:
                    notes_obj = json.loads(row.notes) if row.notes else {}
                except Exception:
                    notes_obj = {}
                if notes_obj.get("user_id") != user_id:
                    continue

            results.append(SymptomLog.model_validate(row, from_attributes=True))

        return results

def get_log(log_id: str) -> SymptomLog | None:
    with session_scope() as db:
        row = db.get(SymptomLogORM, log_id)
        return (
            SymptomLog.model_validate(row, from_attributes=True) if row else None
        )


def get_entries(user_id: str, since: Optional[datetime] = None) -> List[SymptomLog]:
    """Compatibility wrapper to match the former db/health_db.py interface."""
    return list_logs(user_id=user_id, since=since)