from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from enum import Enum
from typing import List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from dateutil.parser import parse
from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = ["Severity", "SymptomLog", "natural_language_to_datetime"]


class Severity(str, Enum):
    """Standardised severity levels for symptoms."""

    none = "none"
    mild = "mild"
    moderate = "moderate"
    severe = "severe"

    @classmethod
    def _missing_(cls, value: object) -> "Severity":
        if not isinstance(value, str):
            raise ValueError(f"Unknown severity: {value}")
        val = value.strip().lower()
        synonyms = {
            "slight": "mild",
            "light": "mild",
            "average": "moderate",
            "noticeable": "moderate",
            "strong": "severe",
            "intense": "severe",
            "awful": "severe",
            "terrible": "severe",
        }
        if val in synonyms:
            return cls(synonyms[val])
        return super()._missing_(val)


_DEF_TZ = ZoneInfo("UTC")


def _to_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware and converted to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_DEF_TZ)
    return dt.astimezone(_DEF_TZ)


def natural_language_to_datetime(text: str, user_tz: str | None = "UTC") -> datetime:
    """Convert simple natural language expressions to a UTC datetime."""
    tz: ZoneInfo
    try:
        tz = ZoneInfo(user_tz or "UTC")
    except Exception:
        tz = _DEF_TZ

    match = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", text)
    if match:
        dt = parse(match.group(0))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
    else:
        t = text.strip().lower()
        now = datetime.now(tz)
        today = now.date()
        if "this morning" in t:
            dt = datetime.combine(today, time(8, 0), tzinfo=tz)
        elif "this afternoon" in t:
            dt = datetime.combine(today, time(15, 0), tzinfo=tz)
        elif "tonight" in t or "this evening" in t:
            dt = datetime.combine(today, time(20, 0), tzinfo=tz)
        elif "last night" in t:
            dt = datetime.combine(today - timedelta(days=1), time(22, 0), tzinfo=tz)
        elif "yesterday" in t:
            dt = datetime.combine(today - timedelta(days=1), time(12, 0), tzinfo=tz)
        elif "now" in t or "today" in t:
            dt = now
        else:
            dt = parse(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
    return dt.astimezone(_DEF_TZ)


class SymptomLog(BaseModel):
    """Record of a user's symptom observation."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow().replace(tzinfo=_DEF_TZ))
    symptom: str
    severity: Severity
    started_at: datetime
    ended_at: Optional[datetime] = None
    location: Optional[str] = None
    medicines_taken: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("started_at", "ended_at", mode="before")
    def _parse_datetimes(cls, v: datetime | str | None) -> datetime | None:
        if v is None:
            return v
        if isinstance(v, str):
            return natural_language_to_datetime(v)
        return _to_utc(v)

    @field_validator("medicines_taken", mode="before")
    def _parse_meds(cls, v: str | List[str] | None) -> List[str] | None:
        if v is None:
            return None
        if isinstance(v, str):
            parts = [item.strip() for item in v.split(",") if item.strip()]
            return parts
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        raise TypeError("Invalid medicines_taken")

    @model_validator(mode="after")
    def _check_times(self) -> "SymptomLog":
        if self.started_at and self.ended_at:
            if self.started_at > self.ended_at:
                raise ValueError("started_at must be before or equal to ended_at")
        return self

    @property
    def duration(self) -> Optional[int]:
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None
