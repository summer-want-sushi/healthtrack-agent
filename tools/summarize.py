from __future__ import annotations

from typing import List

from llama_index import VectorStoreIndex, ServiceContext, Document
from llama_index.llms import OpenAI

from tools.get_entries import tool_get_entries


_DEF_TEMP = 0.3


def _to_documents(entries: List[str]) -> List[Document]:
    docs: List[Document] = []
    for idx, entry in enumerate(entries):
        text = getattr(entry, "text", None) or str(entry)
        docs.append(Document(text=text, id_=str(idx)))
    return docs


def tool_summarize(user_id: str) -> str:
    """Return a doctor-friendly bullet summary of a user's recent entries."""

    entries = tool_get_entries(user_id)
    if not entries:
        return "No entries found."

    docs = _to_documents(entries[-5:])  # last N entries

    service_context = ServiceContext.from_defaults(
        llm=OpenAI(temperature=_DEF_TEMP)
    )
    index = VectorStoreIndex.from_documents(docs, service_context=service_context)
    query_engine = index.as_query_engine(similarity_top_k=5)
    response = query_engine.query(
        "Summarize the patient's recent symptom entries in concise bullet points for a doctor."
    )
    return str(response).strip()
