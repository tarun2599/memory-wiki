"""Unit tests for transcript processor."""

from unittest.mock import patch

import pytest

from app.services.memory_store import MemoryStore
from app.services.processor import process_transcript_memories
from tests.unit.test_memory_store import FakeStorage


@pytest.fixture
def patched_store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    fake = FakeStorage()
    store = MemoryStore(storage=fake)
    monkeypatch.setattr("app.services.processor.MemoryStore", lambda: store)
    return store


class TestProcessor:
    def test_process_creates_memory_files(self, patched_store: MemoryStore) -> None:
        result = process_transcript_memories(
            "abc-123",
            "Alice and Bob discussed Python APIs for their new project.",
        )
        assert result["memory_count"] > 0
        assert len(result["files_written"]) > 0
        paths = patched_store.get_existing_paths()
        assert len(paths) > 0

    def test_process_updates_index(self, patched_store: MemoryStore) -> None:
        process_transcript_memories("tx-001", "Charlie talked about databases.")
        index = patched_store.storage.get_index()
        assert index is not None
        assert len(index["transcripts"]) == 1
        assert index["transcripts"][0]["id"] == "tx-001"

    def test_process_append_on_second_transcript(self, patched_store: MemoryStore) -> None:
        process_transcript_memories("tx-1", "Alice loves Python.")
        process_transcript_memories("tx-2", "Alice also uses Kubernetes.")
        paths = patched_store.get_existing_paths()
        alice_files = [p for p in paths if "alice" in p]
        assert len(alice_files) >= 1
        content, _, _ = patched_store.storage.get_object(alice_files[0])
        assert "tx-1" in content or "tx-2" in content
