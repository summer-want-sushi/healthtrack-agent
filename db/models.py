"""
SQLAlchemy ↔️ Pydantic mapping for SymptomLog.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON
from uuid import uuid4

from db.engine import Base
from tools.health_schema import Severity

class SymptomLogORM(Base):
    __tablename__ = "symptom_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    symptom = Column(String, nullable=False)
    severity = Column(Enum(Severity), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    location = Column(String)
    medicines_taken = Column(JSON)
    notes = Column(Text)
