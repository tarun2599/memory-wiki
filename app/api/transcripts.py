"""Transcript ingestion and retrieval endpoints."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ProcessingJob, ProcessingStatus, Transcript
from app.schemas import TranscriptCreate, TranscriptIngestResponse, TranscriptResponse
from app.worker import process_transcript_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.post("", response_model=TranscriptIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_transcript(
    body: TranscriptCreate,
    session: AsyncSession = Depends(get_session),
) -> TranscriptIngestResponse:
    """Ingest a conversation transcript. Persists to DB and queues memory extraction."""
    transcript = Transcript(content=body.content, metadata_=body.metadata)
    session.add(transcript)
    await session.flush()

    idempotency_key = hashlib.sha256(f"{transcript.id}:{body.content}".encode()).hexdigest()

    existing = await session.execute(
        select(ProcessingJob).where(ProcessingJob.idempotency_key == idempotency_key)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate transcript submission detected",
        )

    job = ProcessingJob(
        transcript_id=transcript.id,
        status=ProcessingStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    await session.commit()

    process_transcript_task.delay(job.id, transcript.id)
    logger.info("Queued processing job %s for transcript %s", job.id, transcript.id)

    return TranscriptIngestResponse(
        id=transcript.id,
        processing_job_id=job.id,
        status="pending",
        message="Transcript ingested. Memory extraction queued.",
    )


@router.get("/{transcript_id}", response_model=TranscriptResponse)
async def get_transcript(
    transcript_id: str,
    session: AsyncSession = Depends(get_session),
) -> TranscriptResponse:
    """Retrieve a stored transcript by ID."""
    result = await session.execute(select(Transcript).where(Transcript.id == transcript_id))
    transcript = result.scalar_one_or_none()
    if not transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")

    job_result = await session.execute(
        select(ProcessingJob)
        .where(ProcessingJob.transcript_id == transcript_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()
    processing_status = job.status.value if job else None

    return TranscriptResponse(
        id=transcript.id,
        content=transcript.content,
        metadata=transcript.metadata_,
        created_at=transcript.created_at,
        updated_at=transcript.updated_at,
        processing_status=processing_status,
    )
