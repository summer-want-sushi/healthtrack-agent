import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zoneinfo import ZoneInfo
from tools.health_schema import Severity, SymptomLog, natural_language_to_datetime


def test_repo_roundtrip(tmp_path, monkeypatch):
    # Use a temporary database for isolation
    monkeypatch.setenv("HEALTH_DB_PATH", str(tmp_path / "health.db"))
    import importlib
    from db import repository as repo
    importlib.reload(repo)

    # Create a sample log
    dt = natural_language_to_datetime("2024-07-01 08:00", user_tz="America/New_York")
    log = SymptomLog(
        symptom="nausea",
        severity="intense",     # synonym → severe
        started_at=dt,
        location="home",
        medicines_taken=["gravol"],
        notes="before breakfast",
    )
    repo.add_log(log)

    logs = repo.list_logs()
    assert len(logs) == 1
    roundtrip = logs[0]

    # severity synonym mapping
    assert roundtrip.severity is Severity.severe
    # TZ conversion
    assert roundtrip.started_at.tzinfo is ZoneInfo("UTC")
    # duration property
    assert roundtrip.duration is None
