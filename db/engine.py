"""SQLAlchemy engine utilities."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def get_engine() -> Engine:
    """Return an engine bound to ``health.db`` in the current working directory."""

    db_path = Path.cwd() / "health.db"
    url = f"sqlite:///{db_path}"
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )


_initialized_paths: set[Path] = set()


def init_db(engine: Engine | None = None) -> Engine:
    """Initialize database tables if they haven't been created."""

    if engine is None:
        engine = get_engine()

    db_path = Path(engine.url.database or "")
    if db_path not in _initialized_paths:
        from db import models  # noqa: E402 – side-effect import

        Base.metadata.create_all(engine)
        _initialized_paths.add(db_path)

    return engine

