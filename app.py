"""HealthTrack demo exposing FastAPI API and Gradio UI in one process."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import dateparser
import gradio as gr
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import repository as repo
from tools.get_entries import tool_get_entries
from tools.health_schema import SymptomLog
from tools.log_entry import tool_log
from tools.summarize import tool_summarize


logger = logging.getLogger(__name__)

# Ensure OpenAI credentials are loaded from the environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# ---------------------------------------------------------------------------
# Helpers

def _serialise(entry: SymptomLog | Dict[str, Any]) -> Dict[str, Any]:
    """Convert a ``SymptomLog`` (or dict) to JSON-serialisable dict."""

    data = entry.model_dump(exclude_none=True) if isinstance(entry, SymptomLog) else dict(entry)

    for key in ("created_at", "started_at", "ended_at"):
        if val := data.get(key):
            if hasattr(val, "isoformat"):
                data[key] = val.isoformat()

    if (sev := data.get("severity")) and hasattr(sev, "value"):
        data["severity"] = sev.value

    return data


def _log_symptom(user_id: str, text: str) -> Dict[str, Any]:
    """Persist ``text`` for ``user_id`` and return the stored entry."""

    msg = tool_log(text=text, user_id=user_id)
    try:
        entry_id = msg.rsplit(":", 1)[1].strip()
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Unable to parse log entry id") from exc

    entry = repo.get_log(entry_id)
    if not entry:  # pragma: no cover - defensive
        raise RuntimeError("Log entry not found")
    return _serialise(entry)


def _list_entries(user_id: str, since: str | None = None) -> List[Dict[str, Any]]:
    """Return all entries for ``user_id`` optionally filtered by ``since``."""

    entries = [_serialise(e) for e in tool_get_entries(user_id)]

    if since:
        dt = dateparser.parse(since)
        if not dt:
            raise ValueError("Invalid 'since' parameter")
        entries = [
            e
            for e in entries
            if (
                (e.get("started_at") and dateparser.parse(e["started_at"]) >= dt)
                or (e.get("created_at") and dateparser.parse(e["created_at"]) >= dt)
            )
        ]

    return entries


# ---------------------------------------------------------------------------
# FastAPI setup


class LogRequest(BaseModel):
    user_id: str
    text: str


api_router = APIRouter(prefix="/api")


@api_router.post("/log")
def api_log(req: LogRequest):
    """Log a free-form symptom description."""

    try:
        return _log_symptom(req.user_id, req.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Log endpoint failed")
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


@api_router.get("/entries")
def api_entries(
    user_id: str = Query(..., description="User identifier"),
    since: str | None = Query(None, description="Return entries since this date"),
):
    """List logged entries."""

    try:
        return _list_entries(user_id, since)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Entries endpoint failed")
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


@api_router.get("/summary")
def api_summary(user_id: str = Query(..., description="User identifier")):
    """Return a doctor-friendly summary of recent entries."""

    try:
        return {"summary": tool_summarize(user_id)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Summary endpoint failed")
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


fastapi_app = FastAPI()
fastapi_app.include_router(api_router)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "https://localhost",
        "https://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Gradio UI


with gr.Blocks() as demo:
    user_box = gr.Textbox(label="User ID")
    symptom_box = gr.Textbox(label="Symptom description", lines=2)
    log_btn = gr.Button("Log")
    log_output = gr.JSON(label="Saved entry")

    view_btn = gr.Button("View entries")
    entries_output = gr.Dataframe(label="Entries")

    summary_btn = gr.Button("Summarize for doctor")
    summary_output = gr.Markdown()

    log_btn.click(_log_symptom, inputs=[user_box, symptom_box], outputs=log_output)
    view_btn.click(_list_entries, inputs=[user_box], outputs=entries_output)
    summary_btn.click(tool_summarize, inputs=[user_box], outputs=summary_output)


# Mount Gradio UI at `/` and expose FastAPI under `/api`.
app = gr.mount_gradio_app(fastapi_app, demo, path="/")

