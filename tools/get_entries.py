from typing import List, Optional
from datetime import datetime

from db.engine import SessionLocal
from tools.health_schema import SymptomLog
from db.models import SymptomLogORM


def tool_get_entries(user_id: str, since: Optional[str] = None) -> List[dict]:
    """Return symptom logs for ``user_id`` optionally filtered by ``since``."""
    since_dt: Optional[datetime] = None
    if since:
        since_dt = datetime.fromisoformat(since)

    db = SessionLocal()
    try:
        query = db.query(SymptomLogORM).filter(SymptomLogORM.user_id == user_id)
        if since_dt:
            query = query.filter(SymptomLogORM.started_at >= since_dt)
        rows = query.all()
        return [
            SymptomLog.model_validate(row, from_attributes=True).model_dump(exclude_none=True)
            for row in rows
        ]
    finally:
        db.close()
