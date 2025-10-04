from __future__ import annotations

from tools.get_entries import tool_get_entries
from memory.index import query_index
from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding

def _entry_to_doc(entry: dict) -> Document:
    """Convert an entry dictionary to a LlamaIndex Document."""
    text_parts: list[str] = [
        f"Symptom: {entry.get('symptom')}",
        f"Severity: {entry.get('severity')}",
        f"Started: {entry.get('started_at')}",
    ]
    notes = entry.get("notes")
    if notes:
        text_parts.append(f"Notes: {notes}")
    return Document(text="\n".join(text_parts), doc_id=str(entry.get("id")))


def _format_bullets(entries: list[dict]) -> str:
    """Consistent fallback bullet list from recent entries."""

    def fmt(e: dict) -> str:
        sym = e.get("symptom") or "symptom"
        sev = e.get("severity")
        sev = str(sev) if sev is not None else "?"
        when = e.get("started_at") or e.get("created_at") or ""
        loc = e.get("location")
        loc_txt = f" @ {loc}" if loc else ""
        return f"- {sym}{loc_txt} (severity: {sev}) {when}".strip()

    return "\n".join(fmt(e) for e in entries)


def tool_summarize(user_id: str) -> str:
    """
    Create a concise, doctor-friendly summary of a user's recent symptom entries.
    
    The function collects up to five most-recent symptom entries for the given user and attempts to produce a short, doctor-oriented summary. If no entries exist, it returns "No entries found for this user." If the summary generation fails for any reason, it falls back to returning a simple bullet-point listing of the recent entries.
    
    Returns:
        str: A concise doctor-friendly summary based on the user's recent entries, or
        the string "No entries found for this user." if there are no entries. On internal
        errors the returned string will be a bullet-formatted representation of the recent entries.
    """
    entries = tool_get_entries(user_id)
    if not entries:
        return "No entries found for this user."

    # Sort newest first and keep last 5
    entries.sort(
        key=lambda e: e.get("started_at") or e.get("created_at"),
        reverse=True,
    )
    recent = entries[:5]

    ctx = query_index(
        user_id,
        "Summarize this user's recent symptoms in a short, doctor-friendly note.",
        k=8,
    )

    if ctx:
        def _ctx_text(c):
            if isinstance(c, dict):
                return c.get("text", "")
            text = getattr(c, "text", None)
            if text is not None:
                return text
            getter = getattr(c, "get_content", None)
            if callable(getter):
                try:
                    return getter()
                except Exception:
                    return ""
            return str(c)

        snippets = "\n\n".join(_ctx_text(c) for c in ctx[:5])
        prompt = (
            "Given the following symptom logs, provide a concise bullet point "
            "summary suitable for a doctor.\n" + snippets
        )
        try:
            llm = OpenAI(model="gpt-3.5-turbo", temperature=0.3)
            response = llm.complete(prompt)
            return response.text
        except Exception:
            return _format_bullets(recent)

    # Fallback to DB query if retrieval returns nothing
    Settings.llm = None
    embed_model = OpenAIEmbedding(model="text-embedding-3-small")
    Settings.embed_model = embed_model
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
        return _format_bullets(recent)


def summarize(user_id: str, question: str | None = None, days: int = 7) -> str:
    """
    Compatibility wrapper that delegates to `tool_summarize` while preserving a legacy signature.
    
    Parameters:
        user_id (str): Identifier of the user whose entries will be summarized.
        question (str | None): Ignored; accepted for compatibility with callers that pass a question.
        days (int): Ignored; accepted for compatibility with callers that pass a time window.
    
    Returns:
        summary (str): A concise, doctor-friendly summary for the given user.
    """

    _ = question, days
    return tool_summarize(user_id=user_id)