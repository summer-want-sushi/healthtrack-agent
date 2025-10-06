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

## API server

Start the FastAPI server locally:

```bash
python run_api.py
```

The server listens on http://127.0.0.1:8000 (reload enabled). Key endpoints:

- `GET /health` → returns `{ "ok": true }`.
- `POST /log` → body `{ "user_id": "u1", "message": "..." }` stores a symptom entry.
- `GET /entries` → query params `user_id`, optional `since` ISO 8601 timestamp.
- `GET /summary` → query params `user_id`, optional `days` (default 7) and `question`.

Authentication: set `API_TOKEN=your-secret` to require `Authorization: Bearer your-secret` on all requests. If `API_TOKEN` is unset, requests are allowed (development mode).

CORS configuration: set `CORS_ORIGINS` to a comma-separated list to restrict browser origins. Examples:

- Development default: `CORS_ORIGINS="*"`
- Single origin: `CORS_ORIGINS="https://summer-want-sushi-healthtrack-agent.hf.space"`
- Multiple origins: `CORS_ORIGINS="https://app.yourdomain.com, https://yourdomain.com"`

Visit `http://127.0.0.1:8000/ui` for a simple Gradio demo mounted on the API.

Example requests:

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/log \
     -H "Content-Type: application/json" \
     -d '{"user_id":"u1","message":"Headache 6/10 since 8pm, 2h, took Advil"}'

curl "http://127.0.0.1:8000/entries?user_id=u1"

curl "http://127.0.0.1:8000/summary?user_id=u1&days=7"

# With auth
API_TOKEN=secret-token python run_api.py &
curl -H "Authorization: Bearer secret-token" http://127.0.0.1:8000/health
```
