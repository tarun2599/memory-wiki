# Memory Wiki

A service that ingests conversation transcripts, extracts structured memories using an LLM, stores them as a navigable file tree in cloud object storage, and exposes unix-style REST endpoints (`ls`, `cat`, `grep`).

## Quick Start

**Single command to run everything:**

```bash
docker compose up --build
```

This starts:
- **API** at http://localhost:8000 (Swagger docs at http://localhost:8000/docs)
- **Celery worker** for background memory extraction
- **PostgreSQL** for transcript persistence
- **Redis** for task queue
- **MinIO** (S3-compatible) for memory file storage (console at http://localhost:9001)

By default, the LLM runs in **mock mode** (no API key needed). To use OpenAI:

```bash
cp .env.example .env
# Set OPENAI_API_KEY and LLM_PROVIDER=openai
docker compose up --build
```

### Demo

```bash
make demo
```

Or manually:

```bash
# Ingest a transcript
curl -X POST http://localhost:8000/transcripts \
  -H "Content-Type: application/json" \
  -d '{"content": "Alice met Bob to discuss Kubernetes. Alice prefers PostgreSQL.", "metadata": {"participants": ["Alice", "Bob"]}}'

# Wait a few seconds for background processing, then explore memories
curl "http://localhost:8000/memory/ls?path=/"
curl "http://localhost:8000/memory/grep?pattern=kubernetes&ignore_case=true"
curl "http://localhost:8000/memory/tree?depth=3"
```

---

## Architecture

```
┌─────────────┐     POST /transcripts      ┌──────────────┐
│   Client    │ ─────────────────────────► │   FastAPI    │
└─────────────┘                            │     API      │
       │                                   └──────┬───────┘
       │  GET /memory/{ls,cat,grep}               │
       │ ◄────────────────────────────────────────┤
       │                                          │ persist
       │                                          ▼
       │                                   ┌──────────────┐
       │                                   │  PostgreSQL  │
       │                                   │ (transcripts)│
       │                                   └──────────────┘
       │                                          │
       │                                          │ enqueue
       │                                          ▼
       │                                   ┌──────────────┐     ┌─────────────┐
       │                                   │    Redis     │────►│   Celery    │
       │                                   │   (broker)   │     │   Worker    │
       │                                   └──────────────┘     └──────┬──────┘
       │                                                               │
       │                                                               │ LLM extract
       │                                                               ▼
       │                                                        ┌─────────────┐
       └───────────────────────────────────────────────────────►│    MinIO    │
                    read memories                               │  (S3 store) │
                                                                └─────────────┘
```

### Components

| Component | Role |
|-----------|------|
| **FastAPI** | REST API for transcript ingestion and memory navigation |
| **PostgreSQL** | Stores raw transcripts and processing job state |
| **Celery + Redis** | Async background processing with retries |
| **MinIO** | S3-compatible object storage for the memory file tree |
| **OpenAI / Mock LLM** | Extracts structured memories from transcripts |

---

## API Reference

### Transcripts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/transcripts` | Ingest a transcript (returns 202, queues processing) |
| `GET` | `/transcripts/{id}` | Retrieve a stored transcript |

**POST /transcripts** body:
```json
{
  "content": "Conversation text...",
  "metadata": {"participants": ["Alice"], "source": "slack"}
}
```

### Memory (Unix-style)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/memory/ls?path=/` | List directory contents |
| `GET` | `/memory/cat?path=/topics/python.md` | Read a file |
| `GET` | `/memory/grep?pattern=regex&path=/` | Recursive regex search |
| `GET` | `/memory/tree?depth=2` | Nested tree view (bonus) |

**grep parameters:** `pattern` (required), `path`, `ignore_case`, `context` (0–5), `max_results`

---

## Memory File Tree Design

Memories are stored as Markdown files in object storage under the `wiki/` prefix:

```
wiki/
├── _index/
│   └── manifest.json          # Index of all transcripts → files mapping
├── entities/
│   ├── people/
│   │   ├── alice.md           # Person: background, mentions, relationships
│   │   └── bob.md
│   └── organizations/
│       └── acme-corp.md
├── topics/
│   ├── kubernetes.md          # Subject matter knowledge
│   └── python.md
├── preferences/
│   └── communication-style.md # User likes/dislikes/habits
├── events/
│   └── transcript-abc12345.md # Per-transcript event log
├── relationships/
│   └── alice-bob.md
└── facts/
    └── misc.md
```

### Design Decisions

1. **Category-based hierarchy** — Top-level directories mirror memory *types* (entities, topics, preferences, events). This makes `ls` intuitive and `grep` scoped searches natural (`path=/entities/people`).

2. **Kebab-case slugs** — File names are stable identifiers derived from titles (`John Smith` → `john-smith.md`). Slugs are chosen by the LLM but constrained to be grep-friendly.

3. **Markdown format** — Human-readable, supports headers for structure, and greps well. Each file is self-contained.

4. **Metadata on objects** — S3 object metadata stores `title`, `tags`, `confidence`, and `last_transcript` for quick filtering without parsing content.

5. **Manifest index** — `_index/manifest.json` tracks which transcripts contributed to which files, enabling audit trails and future deduplication.

### Update Strategy (New Transcripts → Existing Files)

When a new transcript mentions an existing entity/topic, the LLM returns an `action`:

| Action | Behavior |
|--------|----------|
| `create` | Write a new file |
| `append` | LLM merges new content into existing file (preserving prior knowledge) |
| `update` | LLM reconciles/corrects existing content with new information |

The merge prompt explicitly preserves existing facts, deduplicates, and appends a `## Sources` section listing contributing transcript IDs.

---

## Background Processing

Transcript ingestion is **async by design**:

1. Transcript persisted to PostgreSQL immediately (202 Accepted)
2. Processing job created with **idempotency key** (SHA-256 of transcript ID + content)
3. Celery task queued to Redis
4. Worker calls LLM → writes memory files → updates job status

**Reliability features:**
- **Idempotency** — Duplicate submissions rejected with 409
- **Retries** — Celery retries with exponential backoff (3 attempts, 30s base delay)
- **Late ack** — Tasks acknowledged after completion (not lost on worker crash)
- **Job tracking** — Status: `pending` → `processing` → `completed` / `failed`

---

## Prompt Engineering

### Extraction Prompt
- Returns structured JSON with category, slug, content, tags, confidence, and action
- Receives list of existing memory paths so the LLM can decide create vs. append
- Instructs grep-friendly content (synonyms, key terms)
- Skips trivial small talk

### Merge Prompt
- Takes existing file + new content + merge hint
- Preserves existing information, integrates without duplication
- Adds provenance via Sources section

### Mock Provider
Deterministic regex-based extraction for local dev and CI — finds capitalized names, keyword topics, and creates event logs. No API key required.

---

## Testing

```bash
# All tests
make test

# By layer
make test-unit          # Memory store, LLM, processor logic
make test-integration   # S3 via moto
make test-e2e           # Full API flow
```

### Testing Pyramid

| Layer | What's tested | Tools |
|-------|--------------|-------|
| **Unit** | Memory store ls/cat/grep, mock LLM extraction/merge, processor | pytest, FakeStorage |
| **Integration** | S3 put/get/list against moto | pytest, moto |
| **E2E** | HTTP API ingest → memory grep | pytest, httpx, mocked DB |

**Edge cases covered:**
- Empty directories, nested paths
- cat on directory (400), missing file (404)
- Invalid grep regex (400)
- Append vs. create on duplicate entities
- Idempotent merge (Sources section)

---

## Project Structure

```
├── app/
│   ├── main.py              # FastAPI entry
│   ├── config.py            # Settings (pydantic-settings)
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # Async session
│   ├── schemas.py           # Pydantic request/response models
│   ├── worker.py            # Celery app + task
│   ├── api/
│   │   ├── transcripts.py   # POST/GET transcripts
│   │   └── memory.py        # ls, cat, grep, tree
│   └── services/
│       ├── storage.py       # S3/MinIO abstraction
│       ├── memory_store.py  # Unix-style file operations
│       ├── llm.py           # OpenAI + mock providers
│       └── processor.py     # Transcript → memory pipeline
├── alembic/                 # DB migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docker-compose.yml
├── Dockerfile
└── Makefile
```

---

## Assumptions & Tradeoffs

### Assumptions
- **Single-tenant** — One memory wiki (no per-user isolation). Multi-tenancy would add a `{user_id}/` prefix.
- **English transcripts** — Prompts optimized for English conversation.
- **Markdown is sufficient** — No binary/media memories.
- **Eventual consistency** — Memories available seconds after ingest (async processing).
- **Mock LLM is acceptable for eval** — Demonstrates full pipeline without API costs.

### Tradeoffs

| Decision | Chosen | Alternative | Why |
|----------|--------|-------------|-----|
| Object storage vs. DB for memories | S3/MinIO file tree | PostgreSQL JSONB | Matches unix metaphor, scales to large files, natural ls/cat/grep |
| Async processing | Celery + Redis | Sync inline | LLM calls are slow (2–10s); async keeps API responsive |
| Merge via LLM | LLM merge prompt | CRUD append-only | Smarter dedup and reconciliation; costlier but higher quality |
| Mock LLM default | Regex mock | Require API key | Zero-friction local demo |
| REST query params | `/memory/ls?path=` | Path-based `/memory/ls/*` | Cleaner URL encoding for arbitrary paths |

---

## What I Would Do With More Time

1. **Semantic search** — Add embedding-based `/memory/search` alongside grep (vector store + hybrid retrieval).
2. **Multi-tenancy** — Namespace memory trees per user/org with auth (JWT + row-level isolation).
3. **Conflict resolution UI** — When `update` actions contradict prior memories, queue for human review.
4. **Streaming ingest** — WebSocket endpoint for live conversation capture.
5. **Memory decay & confidence** — Score memories by recency and confidence; archive stale files.
6. **Deduplication pass** — Periodic background job to merge near-duplicate entity files.
7. **Observability** — OpenTelemetry tracing across API → worker → LLM → S3; Prometheus metrics.
8. **Production hardening** — Dead letter queue, circuit breaker for LLM, S3 versioning for file history.
9. **Anthropic / local model support** — Provider abstraction with fallback chain.
10. **Full testcontainers e2e** — Spin up real Postgres + Redis + MinIO in CI for true integration tests.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgres async URL | PostgreSQL connection |
| `REDIS_URL` | redis://localhost:6379/0 | Celery broker |
| `S3_ENDPOINT` | http://localhost:9000 | MinIO/S3 endpoint |
| `S3_BUCKET` | memories | Bucket name |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `LLM_PROVIDER` | mock | `mock` or `openai` |
| `LOG_LEVEL` | INFO | Logging level |

---

## License

MIT
