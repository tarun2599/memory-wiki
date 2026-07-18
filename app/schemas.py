from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptCreate(BaseModel):
    content: str = Field(..., min_length=1, description="Raw conversation transcript text")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata (participants, source, etc.)")


class TranscriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    processing_status: str | None = None


class TranscriptIngestResponse(BaseModel):
    id: str
    processing_job_id: str
    status: str
    message: str


class MemoryEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" or "directory"
    size: int | None = None
    last_modified: datetime | None = None


class LsResponse(BaseModel):
    path: str
    entries: list[MemoryEntry]


class CatResponse(BaseModel):
    path: str
    content: str
    content_type: str = "text/markdown"
    last_modified: datetime | None = None
    metadata: dict[str, Any] | None = None


class GrepMatch(BaseModel):
    path: str
    line_number: int
    line: str
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)


class GrepResponse(BaseModel):
    pattern: str
    path: str
    matches: list[GrepMatch]
    total_matches: int


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
