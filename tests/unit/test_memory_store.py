"""Unit tests for memory store and LLM services."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm import MockLLMProvider
from app.services.memory_store import MemoryStore


class FakeStorage:
    """In-memory fake for ObjectStorage."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.metadata: dict[str, dict] = {}
        self.prefix = "wiki/"

    def _full_key(self, path: str) -> str:
        normalized = path.strip("/")
        return f"{self.prefix}{normalized}" if normalized else self.prefix

    def _relative_path(self, key: str) -> str:
        return key[len(self.prefix) :] if key.startswith(self.prefix) else key

    def list_objects(self, directory: str = "") -> list[dict]:
        prefix = self._full_key(directory)
        if prefix != self.prefix and not prefix.endswith("/"):
            prefix += "/"

        dirs: set[str] = set()
        files: dict[str, dict] = {}

        for key in self.files:
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix) :]
            if not remainder:
                continue
            if "/" in remainder:
                dir_name = remainder.split("/")[0]
                dirs.add(dir_name)
            else:
                files[remainder] = {
                    "name": remainder,
                    "path": self._relative_path(key),
                    "type": "file",
                    "size": len(self.files[key]),
                }

        entries = [{"name": d, "path": self._relative_path(prefix + d), "type": "directory"} for d in sorted(dirs)]
        entries.extend(files.values())
        return sorted(entries, key=lambda e: (e["type"] != "directory", e["name"]))

    def get_object(self, path: str) -> tuple[str, dict | None, None]:
        key = self._full_key(path)
        if key not in self.files:
            raise FileNotFoundError(path)
        return self.files[key], self.metadata.get(key), None

    def put_object(self, path: str, content: str, metadata: dict | None = None) -> str:
        key = self._full_key(path)
        self.files[key] = content
        if metadata:
            self.metadata[key] = metadata
        return key

    def object_exists(self, path: str) -> bool:
        return self._full_key(path) in self.files

    def list_all_files(self, directory: str = "") -> list[str]:
        prefix = self._full_key(directory)
        if prefix != self.prefix and not prefix.endswith("/"):
            prefix += "/"
        return [
            self._relative_path(k)
            for k in self.files
            if k.startswith(prefix) and not k.endswith("/") and k != prefix
        ]

    def put_index(self, index_data: dict) -> None:
        self.put_object("_index/manifest.json", json.dumps(index_data))

    def get_index(self) -> dict | None:
        try:
            content, _, _ = self.get_object("_index/manifest.json")
            return json.loads(content)
        except FileNotFoundError:
            return None


@pytest.fixture
def fake_store() -> MemoryStore:
    return MemoryStore(storage=FakeStorage())


class TestMemoryStore:
    def test_ls_root_empty(self, fake_store: MemoryStore) -> None:
        result = fake_store.ls("")
        assert result.path == "/"
        assert result.entries == []

    def test_write_and_ls(self, fake_store: MemoryStore) -> None:
        fake_store.write_memory_file("entities/people", "john-smith", "# John Smith\n\nEngineer.")
        result = fake_store.ls("entities/people")
        assert len(result.entries) == 1
        assert result.entries[0].name == "john-smith.md"
        assert result.entries[0].type == "file"

    def test_cat_file(self, fake_store: MemoryStore) -> None:
        fake_store.write_memory_file("topics", "python", "# Python\n\nA programming language.")
        result = fake_store.cat("topics/python.md")
        assert "Python" in result.content
        assert result.path == "/topics/python.md"

    def test_cat_directory_raises(self, fake_store: MemoryStore) -> None:
        with pytest.raises(IsADirectoryError):
            fake_store.cat("topics")

    def test_cat_missing_file(self, fake_store: MemoryStore) -> None:
        with pytest.raises(FileNotFoundError):
            fake_store.cat("nonexistent/file.md")

    def test_grep_finds_matches(self, fake_store: MemoryStore) -> None:
        fake_store.write_memory_file("entities/people", "alice", "# Alice\n\nLoves Kubernetes.")
        fake_store.write_memory_file("topics", "kubernetes", "# Kubernetes\n\nContainer orchestration.")
        result = fake_store.grep("kubernetes", ignore_case=True)
        assert result.total_matches >= 1
        paths = {m.path for m in result.matches}
        assert any("kubernetes" in p or "alice" in p for p in paths)

    def test_grep_invalid_pattern(self, fake_store: MemoryStore) -> None:
        with pytest.raises(ValueError, match="Invalid regex"):
            fake_store.grep("[invalid")

    def test_grep_with_context(self, fake_store: MemoryStore) -> None:
        content = "line1\nline2 match here\nline3\nline4"
        fake_store.write_memory_file("test", "file", content)
        result = fake_store.grep("match", context=1)
        assert len(result.matches) == 1
        assert result.matches[0].context_before == ["line1"]
        assert result.matches[0].context_after == ["line3"]

    def test_nested_directory_ls(self, fake_store: MemoryStore) -> None:
        fake_store.write_memory_file("entities/people", "bob", "# Bob")
        fake_store.write_memory_file("entities/organizations", "acme", "# Acme")
        result = fake_store.ls("entities")
        names = {e.name for e in result.entries}
        assert "people" in names
        assert "organizations" in names


class TestMockLLMProvider:
    def test_extract_memories_finds_names(self) -> None:
        provider = MockLLMProvider()
        result = provider.extract_memories(
            "Alice met with Bob to discuss Kubernetes deployment.",
            [],
            "test-transcript-id",
        )
        assert "memories" in result
        assert len(result["memories"]) >= 2
        categories = {m["category"] for m in result["memories"]}
        assert "entities/people" in categories or "topics" in categories

    def test_extract_memories_append_action(self) -> None:
        provider = MockLLMProvider()
        existing = ["entities/people/alice.md"]
        result = provider.extract_memories("Alice said hello again.", existing, "tx-2")
        alice_mem = next((m for m in result["memories"] if m["slug"] == "alice"), None)
        assert alice_mem is not None
        assert alice_mem["action"] == "append"

    def test_merge_preserves_existing(self) -> None:
        provider = MockLLMProvider()
        existing = "# Alice\n\nEngineer at Acme."
        new = "Alice now leads the platform team."
        merged = provider.merge_memory_content(existing, new, "Update role", "tx-3")
        assert "Engineer at Acme" in merged
        assert "platform team" in merged
        assert "tx-3" in merged
