from __future__ import annotations

from typing import List

from db.repository import list_logs
from tools.health_schema import SymptomLog


def tool_get_entries(user_id: str) -> List[SymptomLog]:
    """Return all symptom logs for the given user.

    Current implementation ignores the ``user_id`` because user handling
    is not yet implemented. The interface remains to support future
    multi-user storage.
    """

    # In a real application we would filter by ``user_id``.
    return list_logs()
