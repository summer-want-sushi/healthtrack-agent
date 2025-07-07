"""
SQLAlchemy engine + Session factory
"""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_PATH = Path(__file__).resolve().parent.parent / "health.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite multithread
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Create tables as soon as module is imported
from db import models  # noqa: E402 – side-effect import
Base.metadata.create_all(engine)
