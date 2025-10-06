from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# We import the server AFTER monkeypatching env when needed
def make_app(monkeypatch, api_token=None, fakes=None):
    if api_token is not None:
        monkeypatch.setenv("API_TOKEN", api_token)
    else:
        monkeypatch.delenv("API_TOKEN", raising=False)

    # Default fakes if not provided
    fakes = fakes or {}

    # Build fake tool functions
    fake_log = fakes.get("log_entry") or (lambda user_id, message: {
        "user_id": user_id, "main_symptom": "headache", "severity": 6,
        "timestamp": datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
        "notes": message
    })

    def fake_entries(user_id, since=None):
        # record what we received for assertions
        fake_entries.called_with = {"user_id": user_id, "since": since}
        # return two rows
        return [
            {"user_id": user_id, "main_symptom": "fever", "severity": 4,
             "timestamp": datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc).isoformat()},
            {"user_id": user_id, "main_symptom": "cough", "severity": 2,
             "timestamp": datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc).isoformat()},
        ]

    fake_sum = fakes.get("summarize") or (lambda user_id, question="Summarize my recent symptoms.", days=7:
                                          f"Summary for {user_id}: {question} (last {days} days)")

    # Monkeypatch tool entrypoints before importing the app
    import tools.get_entries as ge
    import tools.log_entry as le
    import tools.summarize as su
    monkeypatch.setattr(le, "log_entry", fake_log, raising=True)
    monkeypatch.setattr(ge, "get_entries", fake_entries, raising=True)
    monkeypatch.setattr(su, "summarize", fake_sum, raising=True)

    # Import / reload server after patches so it sees the fakes & env
    server_main = importlib.import_module("server.main")
    importlib.reload(server_main)
    return server_main.app, fake_entries


@pytest.fixture
def client_no_auth(monkeypatch):
    app, _ = make_app(monkeypatch, api_token=None)
    return TestClient(app)


@pytest.fixture
def client_with_auth(monkeypatch):
    app, _ = make_app(monkeypatch, api_token="secrettoken")
    return TestClient(app)


def test_health(client_no_auth):
    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_auth_disabled_allows_requests(client_no_auth):
    r = client_no_auth.get("/entries", params={"user_id": "u1"})
    assert r.status_code == 200


def test_auth_enabled_blocks_without_header(client_with_auth):
    r = client_with_auth.get("/entries", params={"user_id": "u1"})
    assert r.status_code == 401


def test_auth_enabled_allows_with_header(monkeypatch):
    app, _ = make_app(monkeypatch, api_token="secrettoken")
    client = TestClient(app)
    r = client.get("/entries", params={"user_id": "u1"}, headers={"Authorization": "Bearer secrettoken"})
    assert r.status_code == 200


def test_post_log_returns_json(client_no_auth):
    payload = {"user_id": "u1", "message": "Headache 6/10 since 8pm"}
    r = client_no_auth.post("/log", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["main_symptom"] == "headache"
    assert "timestamp" in body


def test_entries_passes_since_as_tzaware(monkeypatch):
    app, fake_entries = make_app(monkeypatch, api_token=None)
    client = TestClient(app)
    r = client.get("/entries", params={"user_id": "u1", "since": "2025-01-01T00:00:00"})
    assert r.status_code == 200
    # Assert the tool was called with tz-aware datetime
    called = fake_entries.called_with
    assert called["user_id"] == "u1"
    assert isinstance(called["since"], datetime)
    assert called["since"].tzinfo is not None


def test_entries_bad_since_returns_400(monkeypatch):
    app, _ = make_app(monkeypatch, api_token=None)
    client = TestClient(app)
    r = client.get("/entries", params={"user_id": "u1", "since": "not-a-date"})
    assert r.status_code == 400


def test_summary_returns_text_field(client_no_auth):
    r = client_no_auth.get("/summary", params={"user_id": "u1", "days": 7})
    assert r.status_code == 200
    j = r.json()
    assert "summary" in j
    assert isinstance(j["summary"], str)
