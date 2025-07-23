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


# Create tables using the default engine at import time so interactive usage
# behaves as expected. Individual sessions may use engines pointing elsewhere.
from db import models  # noqa: E402 – side-effect import
Base.metadata.create_all(get_engine())

