"""Celery worker for async transcript processing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import ProcessingJob, ProcessingStatus
from app.services.processor import process_transcript_memories

logger = logging.getLogger(__name__)

celery_app = Celery("memory_wiki", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=settings.celery_retry_backoff,
    task_max_retries=settings.celery_max_retries,
)

_engine = create_async_engine(settings.database_url, echo=False)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _update_job(
    job_id: str,
    status: ProcessingStatus,
    *,
    error_message: str | None = None,
    files_written: list | None = None,
) -> None:
    async with _session_factory() as session:
        result = await session.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = status
        if status == ProcessingStatus.PROCESSING:
            job.started_at = datetime.now(timezone.utc)
        if status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
            job.completed_at = datetime.now(timezone.utc)
        if error_message:
            job.error_message = error_message
        if files_written is not None:
            job.files_written = files_written
        await session.commit()


async def _get_transcript_content(transcript_id: str) -> str | None:
    from app.models import Transcript

    async with _session_factory() as session:
        result = await session.execute(select(Transcript).where(Transcript.id == transcript_id))
        transcript = result.scalar_one_or_none()
        return transcript.content if transcript else None


@celery_app.task(bind=True, name="process_transcript", max_retries=settings.celery_max_retries)
def process_transcript_task(self, job_id: str, transcript_id: str) -> dict:
    """Background task: extract memories from transcript and write to object storage."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(_update_job(job_id, ProcessingStatus.PROCESSING))

        content = loop.run_until_complete(_get_transcript_content(transcript_id))
        if not content:
            loop.run_until_complete(
                _update_job(job_id, ProcessingStatus.FAILED, error_message="Transcript not found")
            )
            return {"status": "failed", "error": "Transcript not found"}

        result = process_transcript_memories(transcript_id, content)

        loop.run_until_complete(
            _update_job(
                job_id,
                ProcessingStatus.COMPLETED,
                files_written=result["files_written"],
            )
        )
        logger.info("Completed processing job %s: %d files written", job_id, len(result["files_written"]))
        return {"status": "completed", **result}

    except Exception as exc:
        logger.exception("Failed processing job %s", job_id)
        loop.run_until_complete(
            _update_job(job_id, ProcessingStatus.FAILED, error_message=str(exc))
        )
        raise self.retry(exc=exc, countdown=settings.celery_retry_backoff * (2 ** self.request.retries))
    finally:
        loop.close()
