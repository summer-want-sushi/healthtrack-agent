from __future__ import annotations

import json
from typing import List

from db.engine import SessionLocal
from db.models import SymptomLogORM
from tools.health_schema import SymptomLog


def tool_get_entries(user_id: str) -> List[dict]:
    """Return all symptom log entries belonging to ``user_id``."""
    db = SessionLocal()
    try:
        rows = db.query(SymptomLogORM).all()
        result: List[dict] = []
        for row in rows:
            try:
                notes = json.loads(row.notes) if row.notes else {}
            except Exception:
                notes = {}
            if notes.get("user_id") == user_id:
                result.append(
                    SymptomLog.model_validate(row, from_attributes=True).model_dump(
                        exclude_none=True
                    )
                )
        return result
    finally:
        db.close()
