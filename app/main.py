"""Memory Wiki — FastAPI application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import memory, transcripts
from app.config import settings
from app.schemas import ErrorResponse

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Memory Wiki",
    description=(
        "Ingest conversation transcripts, extract memories via LLM, "
        "store them as a navigable file tree in object storage, "
        "and expose unix-style REST endpoints (ls, cat, grep)."
    ),
    version="1.0.0",
)

app.include_router(transcripts.router)
app.include_router(memory.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error", error_code="INTERNAL_ERROR").model_dump(),
    )
