"""HealthTrack demo exposing FastAPI API and Gradio UI in one process."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

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


def log_entry(user_id: str, message: str):
    """
    Create a symptom log entry from free-form text for the specified user.
    
    Parameters:
        user_id (str): Identifier of the user who generated the log.
        message (str): Free-form symptom text to record.
    
    Returns:
        The created log entry (e.g., a SymptomLog instance or a dict) containing the stored entry's data.
    """

    return tool_log(text=message, user_id=user_id)


def get_entries(user_id: str, since: Optional[str] = None):
    """
    Retrieve all entries for a user, optionally filtering to entries on or after a given date/time.
    
    Parameters:
        since (str | None): Optional human-readable date/time string. When provided, entries whose `started_at`
            or `created_at` timestamp is on or after the parsed date/time are returned.
    
    Returns:
        list[dict]: A list of entry dictionaries for the user. If `since` is provided and successfully parsed,
            only entries meeting the timestamp filter are returned; otherwise all entries are returned.
    """

    entries = tool_get_entries(user_id=user_id)
    if since:
        dt = dateparser.parse(since)
        if dt:
            filtered = []
            for entry in entries:
                started = entry.get("started_at")
                created = entry.get("created_at")
                ts = dateparser.parse(started) if started else None
                if not ts and created:
                    ts = dateparser.parse(created)
                if ts and ts >= dt:
                    filtered.append(entry)
            return filtered
    return entries


def summarize(user_id: str, question: str | None = None, days: int = 7):
    """
    Produce a doctor-friendly summary of a user's recent symptom logs.
    
    Parameters:
        user_id (str): Identifier of the user whose entries will be summarized.
        question (str | None): Optional guiding question for the summary (currently accepted for compatibility but ignored).
        days (int): Optional lookback window in days (currently accepted for compatibility but ignored).
    
    Returns:
        str: Summary text suitable for a clinician describing the user's recent symptom history.
    """

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
    """
    Determine whether a user message likely represents a symptom log entry.
    
    Checks for presence of symptom-related keywords or time-related phrases to decide if the text resembles a logging request.
    
    Parameters:
        text (str): The user-provided message to evaluate.
    
    Returns:
        `True` if the text likely represents a symptom log entry, `False` otherwise.
    """

    t = text.lower()
    symptomy = any(w in t for w in SYMPTOM_HINTS)
    timey = bool(TIME_HINT_RE.search(t))
    return symptomy or timey


def _is_summarize_intent(text: str) -> bool:
    """
    Detect whether the given text expresses an intent to request a summary or overview.
    
    Parameters:
        text (str): Input text to analyze for summarization intent.
    
    Returns:
        bool: True if the text contains keywords indicating a request for a summary or overview (e.g., "summarize", "summary", "trend", "overview", "doctor"), False otherwise.
    """
    return bool(re.search(r"\b(summarize|summary|trend|overview|doctor)\b", text, re.I))


def _is_list_intent(text: str) -> bool:
    """
    Detects whether the input text expresses an intent to list or show entries or logs.
    
    Returns:
        `true` if the text contains keywords like "show", "list", "entries", or "log(s)", `false` otherwise.
    """
    return bool(re.search(r"\b(show|list|entries|logs?)\b", text, re.I))


def format_confirmation(result) -> str:
    """
    Create a concise user-facing confirmation message from a tool result.
    
    Parameters:
        result: The tool output to format. May be an object with attributes
            `main_symptom` or `symptom`, `severity`, `timestamp`, and
            `medicines_taken`, or a list/tuple of entries, or any other value.
    
    Returns:
        A short string suitable for display:
        - If symptom/ severity/ timestamp/ medicines are present, returns a
          "Logged: ..." message containing the main symptom, severity as "(<severity>/10)",
          a "since <timestamp>" clause when available, and "meds: <medicines_taken>" when present.
        - If `result` is a list or tuple, returns "`<n>` entry/entries found."
        - Otherwise returns str(result).
    """

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
    """
    Route a user's free-form message to an appropriate action using rule-based heuristics.
    
    The router handles, in order: explicit slash commands (`/log`, `/entries`, `/sum`), explicit summarize or list intents, a symptom-logging heuristic, and a default summary fallback. It returns a formatted confirmation for logging and listing actions or a summary string for summarization requests.
    
    Parameters:
        user_id (str): Identifier of the user whose data the action should apply to.
        text (str): The user's message or command to be routed.
    
    Returns:
        str: A user-facing response produced by the chosen action (confirmation, serialized entries, or summary).
    """

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
    """
    Route a user message through a small LlamaIndex agent that selects and invokes exactly one tool (log_entry, get_entries, or summarize) and returns the agent's textual response.
    
    Returns:
        str: The agent's chosen tool output or response text.
    
    Raises:
        RuntimeError: If the agent returns an empty, indecisive, or error-like response.
    """

    from llama_index.core.agent import ReActAgent
    from llama_index.core.tools import FunctionTool
    from llama_index.llms.openai import OpenAI

    def _tool(fn, name, desc):
        """
        Create a FunctionTool configured with the given callable, name, and description.
        
        Parameters:
            fn (callable): The Python function to expose as a tool.
            name (str): The identifier to register the tool under.
            desc (str): A short human-readable description of the tool's purpose.
        
        Returns:
            FunctionTool: A FunctionTool instance created with the provided function, name, and description.
        """
        return FunctionTool.from_defaults(fn=fn, name=name, description=desc)

    t_log = _tool(
        lambda user_id, message: log_entry(user_id=user_id, message=message),
        "log_entry",
        "Parse free-text symptom note, save to DB, and update the index.",
    )
    t_entries = _tool(
        lambda user_id, since=None: get_entries(user_id=user_id, since=since),
        "get_entries",
        "List recent symptom logs for the user.",
    )
    t_sum = _tool(
        lambda user_id, question="Summarize my recent symptoms.", days=7: summarize(
            user_id=user_id, question=question, days=days
        ),
        "summarize",
        "Concise, doctor-friendly summary grounded in recent entries.",
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
    """
    Route an incoming user message to the configured router and return a user-facing response.
    
    If ROUTER_MODE is "llamaindex", attempt to use the LlamaIndex agent and fall back to the heuristic router on failure; otherwise use the heuristic router.
    
    Returns:
        response (str): The routed handler's user-facing response.
    """

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
    """
    Persist a symptom text for a user and return the stored log entry as a serializable dict.
    
    Returns:
        A JSON-serializable dict representing the stored log entry.
    
    Raises:
        ValueError: If the created log entry ID cannot be parsed from the logging response.
        RuntimeError: If the persisted log entry cannot be retrieved from the repository.
    """

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
    """
    Get serialized symptom entries for a user, optionally filtered to entries on or after a given date.
    
    Parameters:
        user_id (str): ID of the user whose entries to retrieve.
        since (str | None): Date/time string to filter entries; only entries with `started_at` or `created_at`
            greater than or equal to this date are returned. If the string cannot be parsed a ValueError is raised.
    
    Returns:
        List[Dict[str, Any]]: A list of serialized entry dictionaries (dates as ISO strings when available).
    
    Raises:
        ValueError: If `since` is provided but cannot be parsed as a date.
    """

    entries = [_serialise(e) for e in get_entries(user_id=user_id)]

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
    """
    Provide a doctor-friendly summary of recent entries for the given user.
    
    Returns:
        dict: Mapping with key "summary" containing the generated summary text.
    
    Raises:
        HTTPException: With status code 500 if generating the summary fails.
    """

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

