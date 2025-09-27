from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import importlib

import pytest
from tools.health_schema import Severity, SymptomLog


class DummyNode:
    def __init__(self, doc):
        """
        Initialize the DummyNode with a wrapped document.
        
        Parameters:
            doc: A document-like object to wrap. Expected to expose an optional `metadata` mapping (used to populate the node's `metadata` attribute) and may expose a `text` attribute accessed by other node methods.
        """
        self._doc = doc
        self.metadata = getattr(doc, "metadata", {})

    def get_content(self) -> str:
        """
        Return the wrapped document's text content.
        
        Returns:
            str: The document's `text` attribute, or an empty string if the attribute is missing.
        """
        return getattr(self._doc, "text", "")

    def get_score(self) -> float:
        """
        Return a constant relevance score for the wrapped document.
        
        Returns:
            score (float): Constant score equal to 1.0.
        """
        return 1.0


class DummyRetriever:
    def __init__(self, docs: List, limit: int):
        """
        Initialize the retriever with a list of documents and a maximum result limit.
        
        Parameters:
            docs (List): Documents to search when retrieving by query.
            limit (int): Maximum number of results to return for a retrieval.
        """
        self._docs = docs
        self._limit = limit

    def retrieve(self, query: str):
        """
        Return DummyNode-wrapped documents whose text contains the given query string (case-insensitive).
        
        Parameters:
        	query (str): Substring to search for within each document's `text` attribute (case-insensitive).
        
        Returns:
        	list[DummyNode]: List of matching DummyNode instances, limited to the retriever's configured maximum.
        """
        query_lc = query.lower()
        matches = [
            DummyNode(doc)
            for doc in self._docs
            if query_lc in getattr(doc, "text", "").lower()
        ]
        return matches[: self._limit]


class DummyStorageContext:
    def __init__(self) -> None:
        """
        Initialize the mock storage context and prepare the list that will record persisted directories.
        
        The instance attribute `persisted_dirs` is an empty list that will collect directory paths passed to `persist`.
        """
        self.persisted_dirs: List = []

    def persist(self, persist_dir):
        """
        Record a persisted directory path for later inspection.
        
        Parameters:
            persist_dir (str): Filesystem path of the directory that was persisted; the path is appended to the instance's `persisted_dirs` list for later verification in tests.
        """
        self.persisted_dirs.append(persist_dir)


class DummyIndex:
    def __init__(self) -> None:
        """
        Initialize an in-memory dummy index used for testing.
        
        Attributes:
            documents (List): Empty list to store inserted document objects.
            storage_context (DummyStorageContext): Mock storage context that captures persisted directories.
        """
        self.documents: List = []
        self.storage_context = DummyStorageContext()

    def insert(self, doc) -> None:
        """
        Append a document to the in-memory index.
        
        Parameters:
            doc: The document object to store in the index's internal documents list.
        """
        self.documents.append(doc)

    def as_retriever(self, similarity_top_k: int = 8):
        """
        Create a retriever configured to search this index's stored documents.
        
        Parameters:
            similarity_top_k (int): Maximum number of matched documents the retriever will return (default 8).
        
        Returns:
            DummyRetriever: A retriever instance that will search the index's stored documents and return up to `similarity_top_k` results.
        """
        return DummyRetriever(self.documents, similarity_top_k)


@pytest.fixture()
def sample_entries() -> List[SymptomLog]:
    """
    Create two sample SymptomLog entries for testing.
    
    Each entry has its `started_at` timestamp set to the current UTC time. The entries are:
    - "Fever" with severity `Severity.mild` and notes "High fever".
    - "Cough" with severity `Severity.moderate` and notes "Persistent cough".
    
    Returns:
        List[SymptomLog]: Two SymptomLog instances populated as described above.
    """
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
        """
        Return the shared test DummyIndex instance regardless of the provided user_id.
        
        Parameters:
            user_id (str): Ignored; present to match the original function signature.
        
        Returns:
            DummyIndex: The module-level dummy_index used by tests.
        """
        return dummy_index

    def fake_persist_dir(user_id: str):
        """
        Create and return a temporary directory path for the given user ID.
        
        Parameters:
            user_id (str): Identifier used as a child directory name under the module-level `tmp_path`.
        
        Returns:
            pathlib.Path: Path to the created directory (guaranteed to exist).
        """
        path = tmp_path / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(memory_index, "build_or_load_index", fake_build_or_load_index)
    monkeypatch.setattr(memory_index, "_persist_dir", fake_persist_dir)

    upsert_entries("u-123", sample_entries)

    results = query_index("u-123", "fever")

    assert any("fever" in result["text"].lower() for result in results)
