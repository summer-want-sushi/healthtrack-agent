from __future__ import annotations

import json
from typing import List

from tools.get_entries import tool_get_entries
from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.llms.openai import OpenAI


def _entry_to_doc(entry: dict) -> Document:
    """Convert an entry dictionary to a LlamaIndex Document."""
    text_parts: List[str] = [
        f"Symptom: {entry.get('symptom')}",
        f"Severity: {entry.get('severity')}",
        f"Started: {entry.get('started_at')}",
    ]
    notes = entry.get("notes")
    if notes:
        text_parts.append(f"Notes: {notes}")
    return Document(text="\n".join(text_parts), doc_id=str(entry.get("id")))


def tool_summarize(user_id: str) -> str:
    """Summarize the recent symptom logs for ``user_id``."""
    entries = tool_get_entries(user_id)
    if not entries:
        return "No entries found for this user."

    # Sort newest first and keep last 5
    entries.sort(
        key=lambda e: e.get("started_at") or e.get("created_at"),
        reverse=True,
    )
    recent = entries[:5]

    # Build a lightweight index over the recent entries
    Settings.llm = None
    Settings.embed_model = None
    docs = [_entry_to_doc(e) for e in recent]
    index = VectorStoreIndex.from_documents(docs)

    prompt = (
        "Provide a concise bullet point summary suitable for a doctor of the "
        "patient's recent symptom entries."
    )

    try:
        Settings.llm = OpenAI(model="gpt-3.5-turbo", temperature=0.3)
        query_engine = index.as_query_engine()
        response = query_engine.query(prompt)
        return str(response)
    except Exception:
        # Fallback to a simple text summary
        bullets = [f"- {e.get('symptom')} ({e.get('severity')})" for e in recent]
        return "\n".join(bullets)
