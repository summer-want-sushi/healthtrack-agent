from __future__ import annotations

from datetime import datetime
from typing import List
import json

from db.engine import SessionLocal
from db.models import SymptomLogORM
from tools.health_schema import SymptomLog


def get_entries(user_id: str, since: datetime | None = None) -> List[SymptomLog]:
    """Return symptom log entries for the given user."""
    db = SessionLocal()
    try:
        query = db.query(SymptomLogORM)
        if since is not None:
            query = query.filter(SymptomLogORM.created_at >= since)
        rows = query.all()
        results: List[SymptomLog] = []
        for row in rows:
            try:
                notes = json.loads(row.notes) if row.notes else {}
            except Exception:
                notes = {}
            if notes.get("user_id") == user_id:
                results.append(SymptomLog.model_validate(row, from_attributes=True))
        return results
    finally:
        db.close()
