# server/main.py
from __future__ import annotations

import logging
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

# --- CORS (configurable) ---
def _parse_cors_origins(env_val: str | None):
    """
    Parse comma-separated origins. If env is None or '*', return ['*'] (dev).
    Otherwise, return a cleaned list like ['https://app.example.com', 'https://example.com'].
    """
    if not env_val or env_val.strip() == "*":
        return ["*"]
    parts = [p.strip() for p in env_val.split(",")]
    return [p for p in parts if p] or ["*"]

_CORS_ORIGINS = _parse_cors_origins(os.getenv("CORS_ORIGINS"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,   # using Bearer token; no cookies needed
    allow_methods=["*"],
    allow_headers=["*"],       # includes 'Authorization'
)

logger = logging.getLogger(__name__)
if _CORS_ORIGINS == ["*"]:
    logger.warning("CORS is permissive ('*'). This is fine for dev but restrict in production via CORS_ORIGINS.")
else:
    logger.info("CORS allowed origins: %s", _CORS_ORIGINS)

# --- Simple Bearer token auth ---
security = HTTPBearer(auto_error=False)
API_TOKEN = os.getenv("API_TOKEN")

def auth_guard(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """
    Enforces optional Bearer token authentication based on the configured API_TOKEN.
    
    If API_TOKEN is not set, allows access. If API_TOKEN is set, requires an incoming Bearer token that matches API_TOKEN and raises HTTP 401 Unauthorized on mismatch.
    
    Returns:
        True if the request is authorized.
    """
    if not API_TOKEN:
        return True
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return True

# --- Helpers ---
def _ensure_aware(dt: datetime) -> datetime:
    """
    Ensure a datetime is timezone-aware by assigning UTC if no timezone is present.
    
    Parameters:
        dt (datetime): A naive or timezone-aware datetime.
    
    Returns:
        datetime: The same datetime instance if it already has tzinfo; otherwise a new datetime with UTC assigned.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _parse_since(since_str: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO 8601 timestamp string into a timezone-aware datetime, or return None when no input is provided.
    
    Parameters:
        since_str (Optional[str]): ISO 8601 datetime string (a trailing "Z" is accepted). If the string has no timezone, UTC is assumed.
    
    Returns:
        datetime | None: A timezone-aware `datetime` parsed from `since_str`, or `None` if `since_str` is falsy.
    
    Raises:
        HTTPException: 400 Bad Request if `since_str` cannot be parsed as an ISO 8601 datetime.
    """
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
    """
    Convert common Python objects into JSON-serializable structures.
    
    This performs a best-effort conversion for Pydantic v2 models (via model_dump), objects with a __dict__ (returns a dict of public attributes and converts nested Pydantic models), lists/tuples (recursively converted), and dicts (recursively converted). If no conversion rule applies, the original object is returned unchanged.
    
    Returns:
        Any: A JSON-serializable representation (dict, list, or primitive) of `obj`, or `obj` itself if it cannot be converted.
    """
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
    """
    Indicate whether the service is healthy.
    
    Returns:
        dict: A JSON-serializable mapping with key `"ok"` set to `True` when the service is healthy.
    """
    return {"ok": True}

class LogRequest(BaseModel):
    user_id: str
    message: str


@app.post("/log")
def api_log(payload: LogRequest, _auth=Depends(auth_guard)):
    """
    Create a log entry for a user and return its JSON-serializable representation.
    
    Parameters:
        payload (LogRequest): Request body containing `user_id` and `message` for the log entry.
    
    Returns:
        dict: JSON-serializable representation of the saved log entry.
    """
    saved = tool_log_entry(user_id=payload.user_id, message=payload.message)
    return _to_jsonable(saved)

@app.get("/entries")
def api_entries(
    user_id: str,
    since: Optional[str] = Query(default=None, description="ISO8601 datetime, UTC assumed if tz missing"),
    _auth=Depends(auth_guard)
):
    """
    Fetches log entries for a user optionally filtered from a given ISO 8601 timestamp.
    
    Parameters:
        user_id (str): Identifier of the user whose entries to retrieve.
        since (Optional[str]): ISO 8601 datetime string; if provided, only entries on or after this time are returned. A trailing "Z" is treated as UTC and timestamps without a timezone are assumed to be UTC.
    
    Returns:
        list: JSON-serializable list of the user's log entries.
    """
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
    """
    Produce a textual summary of a user's recent entries over a given number of days.
    
    Parameters:
        user_id (str): Identifier of the user whose entries will be summarized.
        days (int): Number of days to include in the summary (1–90).
        question (Optional[str]): Prompt that guides the summary; defaults to "Summarize my recent symptoms."
    
    Returns:
        dict: A JSON-serializable object with a single key `summary` containing the generated summary text.
    """
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
        """
        Handle demo UI commands by invoking internal tools and return a text result.
        
        Recognizes three behaviors:
        - If `text` starts with "/entries", returns the user's entries.
        - If `text` starts with "/log", logs the remainder of `text` as a message and returns a short confirmation containing the logged main symptom when available.
        - Otherwise, treats `text` as a summarization prompt and returns the generated summary.
        
        Parameters:
            user_id (str): Identifier of the user to operate on.
            text (str): Command or prompt entered in the demo UI. Commands are parsed from the start of this string.
        
        Returns:
            str: A human-readable string containing entries, a log confirmation, or a summary depending on the command.
        """
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