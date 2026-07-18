"""End-to-end API tests with mocked persistence."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import ProcessingJob, ProcessingStatus, Transcript
from tests.unit.test_memory_store import FakeStorage


@pytest.fixture
async def api_client():
    fake_storage = FakeStorage()
    stored_transcripts: dict[str, Transcript] = {}
    stored_jobs: dict[str, ProcessingJob] = {}

    async def mock_get_session():
        session = AsyncMock()

        async def flush():
            pass

        async def commit():
            pass

        def add(obj):
            if isinstance(obj, Transcript):
                stored_transcripts[obj.id] = obj
            elif isinstance(obj, ProcessingJob):
                stored_jobs[obj.id] = obj

        session.flush = flush
        session.commit = commit
        session.add = add

        async def execute(stmt):
            result = MagicMock()
            params = stmt.compile().params if hasattr(stmt, "compile") else {}

            if "idempotency_key" in str(stmt):
                key = params.get("idempotency_key_1") or params.get("idempotency_key")
                for job in stored_jobs.values():
                    if job.idempotency_key == key:
                        result.scalar_one_or_none = MagicMock(return_value=job)
                        return result
                result.scalar_one_or_none = MagicMock(return_value=None)
                return result

            tid = params.get("id_1") or params.get("id")
            if tid and tid in stored_transcripts:
                result.scalar_one_or_none = MagicMock(return_value=stored_transcripts[tid])
                result.scalar_one = MagicMock(return_value=stored_transcripts[tid])
                return result

            if tid and tid in stored_jobs:
                result.scalar_one_or_none = MagicMock(return_value=stored_jobs[tid])
                result.scalar_one = MagicMock(return_value=stored_jobs[tid])
                return result

            jobs_for_transcript = [j for j in stored_jobs.values() if j.transcript_id == tid]
            if jobs_for_transcript:
                result.scalar_one_or_none = MagicMock(return_value=jobs_for_transcript[-1])
                return result

            result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        session.execute = execute
        yield session

    from app.database import get_session

    app.dependency_overrides[get_session] = mock_get_session

    store = __import__("app.services.memory_store", fromlist=["MemoryStore"]).MemoryStore(storage=fake_storage)

    with patch("app.api.memory._get_store", return_value=store):
        with patch("app.api.transcripts.process_transcript_task") as mock_task:
            def process_sync(job_id, transcript_id):
                t = stored_transcripts.get(transcript_id)
                if t:
                    from app.services.processor import process_transcript_memories

                    with patch("app.services.processor.MemoryStore", return_value=store):
                        process_transcript_memories(transcript_id, t.content)
                    if job_id in stored_jobs:
                        stored_jobs[job_id].status = ProcessingStatus.COMPLETED

            mock_task.delay = process_sync

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, fake_storage

    app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestE2E:
    async def test_health(self, api_client) -> None:
        client, _ = api_client
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_transcript_ingest_and_retrieve(self, api_client) -> None:
        client, _ = api_client
        payload = {
            "content": "Alice and Bob discussed the Kubernetes migration project.",
            "metadata": {"source": "meeting"},
        }
        resp = await client.post("/transcripts", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert "id" in data

        get_resp = await client.get(f"/transcripts/{data['id']}")
        assert get_resp.status_code == 200
        assert "Kubernetes" in get_resp.json()["content"]

    async def test_memory_ls_after_ingest(self, api_client) -> None:
        client, _ = api_client
        await client.post("/transcripts", json={"content": "Charlie uses Python for data pipelines."})

        resp = await client.get("/memory/ls", params={"path": "/"})
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) > 0

    async def test_memory_grep(self, api_client) -> None:
        client, _ = api_client
        await client.post("/transcripts", json={"content": "The team adopted Python for all new API services."})

        resp = await client.get("/memory/grep", params={"pattern": "Python", "ignore_case": True})
        assert resp.status_code == 200
        assert resp.json()["total_matches"] >= 1

    async def test_transcript_not_found(self, api_client) -> None:
        client, _ = api_client
        resp = await client.get("/transcripts/nonexistent-id")
        assert resp.status_code == 404

    async def test_cat_not_found(self, api_client) -> None:
        client, _ = api_client
        resp = await client.get("/memory/cat", params={"path": "/does/not/exist.md"})
        assert resp.status_code == 404

    async def test_grep_invalid_pattern(self, api_client) -> None:
        client, _ = api_client
        resp = await client.get("/memory/grep", params={"pattern": "[bad"})
        assert resp.status_code == 400

    async def test_memory_tree(self, api_client) -> None:
        client, _ = api_client
        await client.post("/transcripts", json={"content": "Eve discussed API design with Frank."})
        resp = await client.get("/memory/tree", params={"depth": 2})
        assert resp.status_code == 200
        assert "children" in resp.json()
