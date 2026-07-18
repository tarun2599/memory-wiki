"""Process transcripts into memory files."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.llm import get_llm_provider
from app.services.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def process_transcript_memories(transcript_id: str, transcript_content: str) -> dict:
    """
    Extract memories from a transcript and write them to object storage.
    Idempotent: re-processing the same transcript produces consistent paths.
    """
    llm = get_llm_provider()
    store = MemoryStore()

    existing_paths = store.get_existing_paths()
    extraction = llm.extract_memories(transcript_content, existing_paths, transcript_id)

    files_written: list[str] = []
    memories = extraction.get("memories", [])

    for memory in memories:
        category = memory["category"]
        slug = memory["slug"]
        content = memory["content"]
        action = memory.get("action", "create")
        merge_hint = memory.get("merge_hint", "")
        path = f"{category}/{slug}.md"

        metadata = {
            "title": memory.get("title", slug),
            "tags": ",".join(memory.get("tags", [])),
            "confidence": str(memory.get("confidence", 0.5)),
            "last_transcript": transcript_id,
        }

        if action in ("append", "update") and store.storage.object_exists(path):
            existing_content, _, _ = store.storage.get_object(path)
            if action == "update" or merge_hint:
                content = llm.merge_memory_content(
                    existing_content, content, merge_hint, transcript_id
                )
            else:
                content = existing_content.rstrip() + "\n\n" + content.strip()
        else:
            # Add frontmatter-style header for new files
            title = memory.get("title", slug)
            if not content.startswith("#"):
                content = f"# {title}\n\n{content}"

        store.write_memory_file(category, slug, content, metadata)
        files_written.append(path)
        logger.info("Wrote memory file: %s (action=%s)", path, action)

    summary = extraction.get("summary", f"Processed transcript {transcript_id}")
    store.update_index(transcript_id, files_written, summary)

    return {
        "files_written": files_written,
        "summary": summary,
        "memory_count": len(memories),
    }
