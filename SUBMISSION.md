# Submission Email Draft

Copy and customize the email below before sending.

---

**Subject:** Memory Wiki Take-Home Submission — Tarun Lakhmani

Hi [Name / Hiring Team],

Please find my submission for the Memory Wiki take-home assignment:

**Repository:** https://github.com/tarun2599/memory-wiki

**Run locally (single command):**
```bash
git clone https://github.com/tarun2599/memory-wiki.git
cd memory-wiki
docker compose up --build
```

The API is available at http://localhost:8000 (Swagger docs at `/docs`). A quick demo is available via `make demo`.

**Highlights:**
- Transcript ingestion with async background processing (Celery + Redis)
- LLM memory extraction with create/append/merge strategy for updates
- Memory store as a navigable S3 file tree with unix-style REST endpoints (`ls`, `cat`, `grep`)
- Testing pyramid: unit, integration (moto S3), and e2e API tests
- Mock LLM mode works out of the box — no API key required for evaluation

Architectural decisions, tradeoffs, and future improvements are documented in the README.

Happy to walk through the design or answer any questions.

Best,
Tarun Lakhmani
[your.email@example.com]
[LinkedIn / phone — optional]
