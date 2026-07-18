"""Memory file tree operations and grep."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.schemas import CatResponse, GrepMatch, GrepResponse, LsResponse, MemoryEntry
from app.services.storage import ObjectStorage


class MemoryStore:
    """Unix-style operations over the memory file tree in object storage."""

    def __init__(self, storage: ObjectStorage | None = None) -> None:
        self.storage = storage or ObjectStorage()

    def ls(self, path: str = "") -> LsResponse:
        normalized = path.strip("/")
        entries_raw = self.storage.list_objects(normalized)

        entries = [
            MemoryEntry(
                name=e["name"],
                path=e["path"],
                type=e["type"],
                size=e.get("size"),
                last_modified=e.get("last_modified"),
            )
            for e in entries_raw
        ]

        return LsResponse(path="/" + normalized if normalized else "/", entries=entries)

    def cat(self, path: str) -> CatResponse:
        normalized = path.strip("/")
        if not normalized:
            raise IsADirectoryError("Cannot cat a directory; use ls instead")

        content, metadata, last_modified = self.storage.get_object(normalized)
        return CatResponse(
            path="/" + normalized,
            content=content,
            last_modified=last_modified,
            metadata=metadata,
        )

    def grep(
        self,
        pattern: str,
        path: str = "",
        ignore_case: bool = False,
        context: int = 0,
        max_results: int = 100,
    ) -> GrepResponse:
        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc

        search_root = path.strip("/")
        file_paths = self.storage.list_all_files(search_root)

        matches: list[GrepMatch] = []
        for file_path in file_paths:
            if file_path.startswith("_index/"):
                continue
            try:
                content, _, _ = self.storage.get_object(file_path)
            except FileNotFoundError:
                continue

            lines = content.splitlines()
            for i, line in enumerate(lines):
                if compiled.search(line):
                    match = GrepMatch(
                        path="/" + file_path,
                        line_number=i + 1,
                        line=line,
                        context_before=lines[max(0, i - context) : i],
                        context_after=lines[i + 1 : i + 1 + context],
                    )
                    matches.append(match)
                    if len(matches) >= max_results:
                        return GrepResponse(
                            pattern=pattern,
                            path="/" + search_root if search_root else "/",
                            matches=matches,
                            total_matches=len(matches),
                        )

        return GrepResponse(
            pattern=pattern,
            path="/" + search_root if search_root else "/",
            matches=matches,
            total_matches=len(matches),
        )

    def write_memory_file(
        self,
        category: str,
        slug: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        path = f"{category}/{slug}.md"
        self.storage.put_object(path, content, metadata)
        return path

    def get_existing_paths(self) -> list[str]:
        return self.storage.list_all_files()

    def update_index(self, transcript_id: str, files_written: list[str], summary: str) -> None:
        index = self.storage.get_index() or {"transcripts": [], "files": {}, "last_updated": None}
        index["transcripts"].append(
            {
                "id": transcript_id,
                "summary": summary,
                "files": files_written,
                "processed_at": datetime.utcnow().isoformat(),
            }
        )
        for f in files_written:
            index["files"][f] = index["files"].get(f, []) + [transcript_id]
        index["last_updated"] = datetime.utcnow().isoformat()
        self.storage.put_index(index)
