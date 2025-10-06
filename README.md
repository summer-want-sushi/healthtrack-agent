---
title: HealthTrack-AI
emoji: 🩺
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
---

## Local demo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q      # run unit tests
python - <<'PY'
from db import repository as repo
from tools.health_schema import SymptomLog
log = SymptomLog(symptom="headache", severity="mild", started_at="now")
repo.add_log(log)
print(repo.list_logs())
PY
```

## Running tests

Ensure all dependencies are installed before executing the test suite:

```bash
pip install -r requirements.txt
pytest -q
```

To run tests against a temporary database, set the ``HEALTH_DB_PATH`` environment
variable to a writable location.
