from __future__ import annotations
from typing import List
from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.embeddings.openai import OpenAIEmbedding
from tools.health_schema import SymptomLog
from db.health_db import get_entries  # implement/adjust import to your Phase-2 CRUD
import os, json, pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
INDEX_ROOT = BASE_DIR / "storage" / "index"
INDEX_ROOT.mkdir(parents=True, exist_ok=True)

def entry_to_document(e: SymptomLog) -> Document:
    """Convert a SymptomLog to a LlamaIndex Document."""
    # Rich, queryable text:
    text = (
        f"Symptom: {e.symptom}\n"
        f"Severity: {e.severity}\n"
        f"Started: {e.started_at.isoformat()}\n"
        f"Ended: {e.ended_at.isoformat() if e.ended_at else 'N/A'}\n"
        f"Location: {e.location or 'N/A'}\n"
        f"Medicines: {', '.join(e.medicines_taken) if e.medicines_taken else 'None'}\n"
        f"Notes: {e.notes or ''}\n"
    )
    metadata = {
        "symptom": e.symptom,
        "severity": e.severity,
        "started_at": e.started_at.isoformat(),
        "ended_at": e.ended_at.isoformat() if e.ended_at else None,
        "location": e.location,
    }
    return Document(text=text, metadata=metadata, doc_id=e.id)

def _persist_dir(user_id: str) -> pathlib.Path:
    d = INDEX_ROOT / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def _embedding() -> OpenAIEmbedding:
    # relies on OPENAI_API_KEY in env
    return OpenAIEmbedding(model="text-embedding-3-small")

def build_or_load_index(user_id: str) -> VectorStoreIndex:
    """Load index for user if exists; otherwise build from DB entries and persist."""
    persist_dir = _persist_dir(user_id)
    if any(persist_dir.iterdir()):
        storage_ctx = StorageContext.from_defaults(persist_dir=persist_dir)
        return load_index_from_storage(storage_ctx)
    # Build fresh
    entries: List[SymptomLog] = get_entries(user_id=user_id, since=None)
    docs = [entry_to_document(e) for e in entries]
    index = VectorStoreIndex.from_documents(docs, embed_model=_embedding())
    index.storage_context.persist(persist_dir=persist_dir)
    return index

def add_entry_to_index(user_id: str, entry: SymptomLog) -> None:
    """Append a single entry to an existing (or new) user index and persist."""
    index = build_or_load_index(user_id)  # loads or builds
    index.insert(entry_to_document(entry))
    index.storage_context.persist(persist_dir=_persist_dir(user_id))

def query_index(user_id: str, question: str, k: int = 8):
    """Return top-k retrieved nodes’ text+metadata for a question."""
    index = build_or_load_index(user_id)
    retriever = index.as_retriever(similarity_top_k=k)
    nodes = retriever.retrieve(question)
    return [
        {
            "text": n.get_content(),
            "score": float(n.get_score() or 0.0),
            "metadata": getattr(n, "metadata", {}) or {},
        }
        for n in nodes
    ]
