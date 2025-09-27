from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import importlib

import pytest
from tools.health_schema import Severity, SymptomLog


class DummyNode:
    def __init__(self, doc):
        self._doc = doc
        self.metadata = getattr(doc, "metadata", {})

    def get_content(self) -> str:
        return getattr(self._doc, "text", "")

    def get_score(self) -> float:
        return 1.0


class DummyRetriever:
    def __init__(self, docs: List, limit: int):
        self._docs = docs
        self._limit = limit

    def retrieve(self, query: str):
        query_lc = query.lower()
        matches = [
            DummyNode(doc)
            for doc in self._docs
            if query_lc in getattr(doc, "text", "").lower()
        ]
        return matches[: self._limit]


class DummyStorageContext:
    def __init__(self) -> None:
        self.persisted_dirs: List = []

    def persist(self, persist_dir):
        self.persisted_dirs.append(persist_dir)


class DummyIndex:
    def __init__(self) -> None:
        self.documents: List = []
        self.storage_context = DummyStorageContext()

    def insert(self, doc) -> None:
        self.documents.append(doc)

    def as_retriever(self, similarity_top_k: int = 8):
        return DummyRetriever(self.documents, similarity_top_k)


@pytest.fixture()
def sample_entries() -> List[SymptomLog]:
    now = datetime.now(timezone.utc)
    return [
        SymptomLog(
            symptom="Fever",
            severity=Severity.mild,
            started_at=now,
            notes="High fever",
        ),
        SymptomLog(
            symptom="Cough",
            severity=Severity.moderate,
            started_at=now,
            notes="Persistent cough",
        ),
    ]


def test_upsert_entries_updates_index(monkeypatch, tmp_path, sample_entries):
    memory_index = importlib.import_module("memory.index")
    upsert_entries = memory_index.upsert_entries
    query_index = memory_index.query_index

    dummy_index = DummyIndex()

    def fake_build_or_load_index(user_id: str):
        return dummy_index

    def fake_persist_dir(user_id: str):
        path = tmp_path / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(memory_index, "build_or_load_index", fake_build_or_load_index)
    monkeypatch.setattr(memory_index, "_persist_dir", fake_persist_dir)

    upsert_entries("u-123", sample_entries)

    results = query_index("u-123", "fever")

    assert any("fever" in result["text"].lower() for result in results)
