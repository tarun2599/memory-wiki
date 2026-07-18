"""LLM-powered memory extraction from conversation transcripts."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI
from slugify import slugify
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction system for a personal knowledge wiki.
Given a conversation transcript, extract structured memories that should be persisted long-term.

Return ONLY valid JSON with this schema:
{
  "memories": [
    {
      "category": "entities/people|entities/organizations|topics|preferences|events|relationships|facts",
      "slug": "kebab-case-identifier",
      "title": "Human readable title",
      "content": "Markdown content for this memory file. Be concise but information-dense.",
      "tags": ["tag1", "tag2"],
      "confidence": 0.0-1.0,
      "action": "create|append|update",
      "merge_hint": "Brief note on how this relates to existing knowledge if action is append/update"
    }
  ],
  "summary": "One-line summary of what was learned from this transcript"
}

Guidelines:
- Extract people, organizations, topics, preferences, events, relationships, and standalone facts
- Use slug names that are stable and descriptive (e.g., "john-smith", "kubernetes-deployment")
- For preferences: capture likes, dislikes, habits, communication style
- For events: include date if mentioned, otherwise use "undated"
- Content should be grep-friendly: include key terms, names, and synonyms
- action=append when adding to an existing entity/topic; action=update when correcting prior info
- Skip trivial small talk; focus on durable knowledge
- Each memory file should be self-contained and readable without the transcript
"""

MERGE_SYSTEM_PROMPT = """You merge new memory content into an existing memory file.
Preserve existing valuable information. Integrate new facts without duplication.
Return ONLY the merged markdown content (no JSON wrapper).
Keep the file well-structured with headers where appropriate.
Add a "## Sources" section at the bottom listing transcript IDs that contributed, if not already present.
"""


class LLMProvider(ABC):
    @abstractmethod
    def extract_memories(
        self,
        transcript: str,
        existing_paths: list[str],
        transcript_id: str,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def merge_memory_content(
        self,
        existing_content: str,
        new_content: str,
        merge_hint: str,
        transcript_id: str,
    ) -> str:
        ...


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def extract_memories(
        self,
        transcript: str,
        existing_paths: list[str],
        transcript_id: str,
    ) -> dict[str, Any]:
        user_prompt = f"""Transcript ID: {transcript_id}

Existing memory paths in the wiki:
{json.dumps(existing_paths[:100], indent=2)}

Transcript:
---
{transcript}
---

Extract memories as JSON."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def merge_memory_content(
        self,
        existing_content: str,
        new_content: str,
        merge_hint: str,
        transcript_id: str,
    ) -> str:
        user_prompt = f"""Merge the following memory files.

Transcript ID: {transcript_id}
Merge hint: {merge_hint}

--- EXISTING ---
{existing_content}

--- NEW ---
{new_content}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MERGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content or existing_content + "\n\n" + new_content


class MockLLMProvider(LLMProvider):
    """Deterministic mock for local dev and testing without API keys."""

    def extract_memories(
        self,
        transcript: str,
        existing_paths: list[str],
        transcript_id: str,
    ) -> dict[str, Any]:
        memories: list[dict[str, Any]] = []

        # Extract names (capitalized words that look like names)
        names = set(re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", transcript))
        for name in names:
            slug = slugify(name)
            action = "append" if f"entities/people/{slug}.md" in existing_paths else "create"
            memories.append(
                {
                    "category": "entities/people",
                    "slug": slug,
                    "title": name,
                    "content": f"# {name}\n\nMentioned in conversation (transcript `{transcript_id}`).\n",
                    "tags": ["person", "mentioned"],
                    "confidence": 0.8,
                    "action": action,
                    "merge_hint": f"Add mention from transcript {transcript_id}",
                }
            )

        # Extract topics from common keywords
        keywords = ["kubernetes", "python", "machine learning", "database", "api", "project"]
        lower = transcript.lower()
        for kw in keywords:
            if kw in lower:
                slug = slugify(kw)
                action = "append" if f"topics/{slug}.md" in existing_paths else "create"
                memories.append(
                    {
                        "category": "topics",
                        "slug": slug,
                        "title": kw.title(),
                        "content": f"# {kw.title()}\n\nDiscussed in transcript `{transcript_id}`.\n",
                        "tags": ["topic"],
                        "confidence": 0.7,
                        "action": action,
                        "merge_hint": f"Add discussion notes from {transcript_id}",
                    }
                )

        # Always create an event entry for the transcript
        memories.append(
            {
                "category": "events",
                "slug": f"transcript-{transcript_id[:8]}",
                "title": f"Conversation {transcript_id[:8]}",
                "content": f"# Conversation Log\n\nTranscript ID: `{transcript_id}`\n\n## Summary\n\n{transcript[:500]}{'...' if len(transcript) > 500 else ''}\n",
                "tags": ["event", "transcript"],
                "confidence": 1.0,
                "action": "create",
                "merge_hint": "",
            }
        )

        return {
            "memories": memories,
            "summary": f"Processed transcript {transcript_id[:8]} with {len(memories)} memories",
        }

    def merge_memory_content(
        self,
        existing_content: str,
        new_content: str,
        merge_hint: str,
        transcript_id: str,
    ) -> str:
        sources_section = f"\n\n## Sources\n- Transcript `{transcript_id}`"
        if "## Sources" in existing_content:
            if transcript_id not in existing_content:
                return existing_content.rstrip() + f"\n- Transcript `{transcript_id}`"
            return existing_content
        merged = existing_content.rstrip() + "\n\n" + new_content.strip()
        if transcript_id not in merged:
            merged += sources_section
        return merged


def get_llm_provider() -> LLMProvider:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider()
    return MockLLMProvider()
