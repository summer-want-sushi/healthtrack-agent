# server/main.py
import os
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Import tools lazily to avoid circular imports at module import time
from tools.log_entry import log_entry as tool_log_entry
from tools.get_entries import get_entries as tool_get_entries
from tools.summarize import summarize as tool_summarize

app = FastAPI(title="HealthTrack-AI API", version="0.1.0")

# --- CORS (open for now; restrict later) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Simple Bearer token auth ---
security = HTTPBearer(auto_error=False)
API_TOKEN = os.getenv("API_TOKEN")

def auth_guard(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Allow all if API_TOKEN not set (dev). Otherwise require matching Bearer token."""
    if not API_TOKEN:
        return True
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return True

# --- Helpers ---
def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _parse_since(since_str: Optional[str]) -> Optional[datetime]:
    if not since_str:
        return None
    try:
        # Accept ISO 8601; assume UTC if no tzinfo present
        dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        return _ensure_aware(dt)
    except Exception:
        # Bad input → 400
        raise HTTPException(status_code=400, detail="Invalid 'since' datetime format. Use ISO 8601.")

def _to_jsonable(obj: Any) -> Any:
    """Best-effort conversion for Pydantic v2 models, ORM rows, or plain dicts/lists."""
    # Pydantic v2 model_dump
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # SQLAlchemy row: try __dict__ but strip private keys
    if hasattr(obj, "__dict__"):
        d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        # Nested pydantic?
        for k, v in list(d.items()):
            if hasattr(v, "model_dump"):
                d[k] = v.model_dump()
        return d
    # List/tuple → recurse
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    # Dict → pass through
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj

# --- Routes ---
@app.get("/health")
def health():
    return {"ok": True}

class LogRequest(BaseModel):
    user_id: str
    message: str


@app.post("/log")
def api_log(payload: LogRequest, _auth=Depends(auth_guard)):
    saved = tool_log_entry(user_id=payload.user_id, message=payload.message)
    return _to_jsonable(saved)

@app.get("/entries")
def api_entries(
    user_id: str,
    since: Optional[str] = Query(default=None, description="ISO8601 datetime, UTC assumed if tz missing"),
    _auth=Depends(auth_guard)
):
    dt = _parse_since(since)
    entries = tool_get_entries(user_id=user_id, since=dt)
    return _to_jsonable(entries)

@app.get("/summary")
def api_summary(
    user_id: str,
    days: int = Query(default=7, ge=1, le=90),
    question: Optional[str] = Query(default="Summarize my recent symptoms."),
    _auth=Depends(auth_guard)
):
    text = tool_summarize(user_id=user_id, question=question or "Summarize my recent symptoms.", days=days)
    # summarize returns plain text → wrap for uniform JSON
    return {"summary": str(text)}


try:
    import gradio as gr
    from gradio.routes import mount_gradio_app

    # Minimal demo UI that calls the API via Python (server-side), not through the browser
    # If you already have a Blocks in another module, import and replace ui below.
    def _ui_predict(user_id, text):
        # Server-side call directly to tools to avoid CORS/auth in demo
        # If you prefer real HTTP calls from browser, build a client-side fetch instead.
        from tools.summarize import summarize as tool_summarize
        from tools.log_entry import log_entry as tool_log_entry
        from tools.get_entries import get_entries as tool_get_entries

        if text.strip().startswith("/entries"):
            return str(tool_get_entries(user_id=user_id))
        if text.strip().startswith("/log"):
            payload = text.strip()[len("/log"):].strip() or text
            res = tool_log_entry(user_id=user_id, message=payload)
            return f"Logged: {getattr(res,'main_symptom',None)}"
        # default to summarize
        return str(tool_summarize(user_id=user_id, question=text))

    with gr.Blocks(title="HealthTrack-AI") as ui:
        gr.Markdown("### HealthTrack-AI — Demo UI  \nTry: `/log Headache 6/10 since 8pm, 2h, took Advil`  ·  `/entries`  ·  `summarize last 7 days`")
        uid = gr.Textbox(label="User ID", value="u1")
        inp = gr.Textbox(label="Message", placeholder="Type a note or command...")
        out = gr.Textbox(label="Response")
        btn = gr.Button("Send")
        btn.click(_ui_predict, inputs=[uid, inp], outputs=[out])

    # Mount at /ui
    app = mount_gradio_app(app, ui, path="/ui")
except Exception:
    # Gradio not installed or mounting failed; API still works
    pass
