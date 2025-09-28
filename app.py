"""HealthTrack demo exposing FastAPI API and Gradio UI in one process."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import dateparser
import gradio as gr
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import repository as repo
from tools.get_entries import get_entries as fetch_entries
from tools.health_schema import SymptomLog
from tools.log_entry import tool_log
from tools.summarize import tool_summarize


logger = logging.getLogger(__name__)

# Ensure OpenAI credentials are loaded from the environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def log_entry(user_id: str, message: str):
    """Adapter exposing ``tool_log`` with a friendlier signature."""

    return tool_log(text=message, user_id=user_id)


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_since(value: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """Parse ``value`` into an aware ``datetime`` or ``None``."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    if not isinstance(value, str):
        raise TypeError("since must be a datetime or ISO-like string")
    dt = dateparser.parse(value)
    if not dt:
        raise ValueError("Invalid 'since' parameter")
    return _ensure_aware(dt)


def get_entries(user_id: str, since: Optional[Union[str, datetime]] = None):
    """Adapter for ``tools.get_entries.get_entries`` with optional parsing."""

    dt = _parse_since(since)
    return fetch_entries(user_id=user_id, since=dt)


def summarize(user_id: str, question: str | None = None, days: int = 7):
    """Adapter for ``tool_summarize`` ignoring extra guidance parameters for now."""

    _ = question, days  # kept for compatibility / future use
    return tool_summarize(user_id=user_id)


ROUTER_MODE = os.getenv("ROUTER_MODE", "heuristic").strip().lower()  # "heuristic" (default) or "llamaindex"

SYMPTOM_HINTS = {
    "pain",
    "ache",
    "numb",
    "tingle",
    "fever",
    "dizzy",
    "dizziness",
    "nausea",
    "vomit",
    "cough",
    "fatigue",
    "headache",
    "migraine",
    "sore",
    "cramp",
    "cramping",
}

TIME_HINT_RE = re.compile(
    r"\b(today|yesterday|this morning|last night|since|for\s+\d+\s+(day|days|week|weeks|hour|hours))\b",
    re.IGNORECASE,
)


def _looks_like_logging(text: str) -> bool:
    """Heuristic: symptom-ish words or time anchors → likely a log request."""

    t = text.lower()
    symptomy = any(w in t for w in SYMPTOM_HINTS)
    timey = bool(TIME_HINT_RE.search(t))
    return symptomy or timey


def _is_summarize_intent(text: str) -> bool:
    return bool(re.search(r"\b(summarize|summary|trend|overview|doctor)\b", text, re.I))


def _is_list_intent(text: str) -> bool:
    return bool(re.search(r"\b(show|list|entries|logs?)\b", text, re.I))


def format_confirmation(result) -> str:
    """Turn tool results into short user-facing text."""

    try:
        main = getattr(result, "main_symptom", None) or getattr(result, "symptom", None)
        sev = getattr(result, "severity", None)
        ts = getattr(result, "timestamp", None)
        meds = getattr(result, "medicines_taken", None)
        if main or sev or ts or meds:
            parts = []
            if main:
                parts.append(str(main))
            if sev is not None:
                parts.append(f"({sev}/10)")
            if ts:
                parts.append(f"since {ts}")
            if meds:
                parts.append(f"meds: {meds}")
            return "Logged: " + " ".join(parts)
        if isinstance(result, (list, tuple)):
            return f"{len(result)} entr{'y' if len(result) == 1 else 'ies'} found."
        return str(result)
    except Exception:
        return str(result)


def heuristic_route(user_id: str, text: str):
    """Rule-based router: slash commands > keywords > symptom heuristic > default summarize."""

    msg = text.strip()
    head = msg.split(" ", 1)[0].lower()

    if head == "/log":
        payload = msg[len("/log"):].strip() or msg
        return format_confirmation(log_entry(user_id=user_id, message=payload))
    if head == "/entries":
        return format_confirmation(get_entries(user_id=user_id))
    if head == "/sum":
        payload = msg[len("/sum"):].strip() or "Summarize my recent symptoms."
        return str(summarize(user_id=user_id, question=payload))

    if _is_summarize_intent(msg):
        return str(summarize(user_id=user_id, question=msg))
    if _is_list_intent(msg):
        return format_confirmation(get_entries(user_id=user_id))

    if _looks_like_logging(msg):
        try:
            return format_confirmation(log_entry(user_id=user_id, message=msg))
        except Exception as e:  # pragma: no cover - guard rails
            logger.exception("log_entry failed; asking for fields")
            return (
                "I couldn't parse that. Please include: symptom, severity (0–10), "
                "and when it started (e.g., 'Headache 6/10 since 8pm, 2h, took Advil')."
            )

    return str(summarize(user_id=user_id, question=msg))


def llamaindex_route(user_id: str, text: str) -> str:
    """Route via a small LlamaIndex agent. Raises on indecision so caller can fallback."""

    from llama_index.core.agent import ReActAgent
    from llama_index.core.tools import FunctionTool
    from llama_index.llms.openai import OpenAI

    t_log = FunctionTool.from_defaults(
        fn=lambda user_id, message: log_entry(user_id=user_id, message=message),
        name="log_entry",
        description="Parse free-text symptom note, save to DB, and update the index.",
    )
    t_entries = FunctionTool.from_defaults(
        fn=lambda user_id, since=None: get_entries(user_id=user_id, since=since),
        name="get_entries",
        description="List recent symptom logs for the user.",
    )
    t_sum = FunctionTool.from_defaults(
        fn=lambda user_id, question="Summarize my recent symptoms.", days=7: summarize(
            user_id=user_id, question=question, days=days
        ),
        name="summarize",
        description="Concise, doctor-friendly summary grounded in recent entries.",
    )

    SYSTEM_PROMPT = (
        "You are HealthTrack-AI. Choose exactly ONE tool that best answers the user.\n"
        "- If the message looks like a symptom note (e.g., 'Headache 6/10 since 8pm…'), use log_entry.\n"
        "- If they ask to see notes, use get_entries.\n"
        "- If they ask for an overview/trends/doctor note, use summarize.\n"
        "Be concise. Never invent data."
    )

    llm = OpenAI(model="gpt-4o-mini", temperature=0.1)
    agent = ReActAgent.from_tools(
        [t_log, t_entries, t_sum], system_prompt=SYSTEM_PROMPT, llm=llm, verbose=False
    )

    prompt = f"user_id={user_id}\n{text}"
    resp = agent.chat(prompt)

    s = str(resp).strip()
    if not s or "ToolExecutionError" in s or "I cannot decide" in s:
        raise RuntimeError("Agent indecision or failure")

    return s


def route_message(user_id: str, text: str) -> str:
    """Main entry: try agent when enabled; otherwise or on failure, use heuristic."""

    if ROUTER_MODE == "llamaindex":
        try:
            return llamaindex_route(user_id=user_id, text=text)
        except Exception as e:  # pragma: no cover - guard rails
            logger.warning("llamaindex_route failed (%s); falling back to heuristic.", e)
            return heuristic_route(user_id=user_id, text=text)
    return heuristic_route(user_id=user_id, text=text)


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

    msg = log_entry(user_id=user_id, message=text)
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

    entries = [_serialise(e) for e in get_entries(user_id=user_id, since=since)]
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
        return {"summary": summarize(user_id=user_id)}
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
    message_box = gr.Textbox(label="Message", lines=3)
    gr.Markdown("Tip: /log …, /entries, /sum …")
    send_btn = gr.Button("Send")
    response_box = gr.Markdown(label="Response")

    send_btn.click(route_message, inputs=[user_box, message_box], outputs=response_box)
    message_box.submit(route_message, inputs=[user_box, message_box], outputs=response_box)


# Mount Gradio UI at `/` and expose FastAPI under `/api`.
app = gr.mount_gradio_app(fastapi_app, demo, path="/")

