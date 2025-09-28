from datetime import datetime
from typing import List, Optional

from db.repository import list_logs
from tools.health_schema import SymptomLog


def get_entries(user_id: str, since: Optional[datetime] = None) -> List[SymptomLog]:
    """Return recent symptom logs for the user, optionally filtered by 'since' (UTC).

    Filtering is delegated to :func:`db.repository.list_logs` so that SQL handles it.
    """

    return list_logs(user_id=user_id, since=since)


def tool_get_entries(user_id: str, since: Optional[datetime] = None) -> List[dict]:
    """Compatibility wrapper that returns serialisable dictionaries."""

    entries = get_entries(user_id=user_id, since=since)
    return [
        entry.model_dump(exclude_none=True)
        if isinstance(entry, SymptomLog)
        else entry
        for entry in entries
    ]
