import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from zoneinfo import ZoneInfo

from tools.health_schema import Severity, SymptomLog, natural_language_to_datetime


def test_severity_synonyms():
    assert Severity("slight") is Severity.mild
    assert Severity("INTENSE") is Severity.severe
    assert Severity("average") is Severity.moderate
    assert Severity("awful") is Severity.severe
    with pytest.raises(ValueError):
        Severity("unknown")


def test_utc_conversion():
    dt = natural_language_to_datetime("2024-06-30 08:00", user_tz="America/New_York")
    log = SymptomLog(symptom="fever", severity="mild", started_at=dt)
    assert log.started_at.tzinfo == ZoneInfo("UTC")
    assert log.started_at.hour == 12


def test_duration_property():
    log = SymptomLog(
        symptom="pain",
        severity="mild",
        started_at="2024-06-30 10:00 UTC",
        ended_at="2024-06-30 10:45 UTC",
    )
    assert log.duration == 2700


if __name__ == "__main__":
    pytest.main([__file__])
