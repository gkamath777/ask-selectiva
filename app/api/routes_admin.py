"""Admin routes: health, etc."""
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.config import get_settings
from app.core.activity_log import list_activity
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.db import crud
from app.db.session import DbSession

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_api_key)])


@router.get("/health")
async def health() -> dict:
    """Health check - no DB dependency."""
    logger.info("health_check")
    return {"status": "healthy", "service": "ask-selectiva"}


@router.get("/activity/logs")
async def activity_logs(since: int = 0, limit: int = 100) -> dict:
    """Return recent structured log events for the in-app activity panel."""
    events = list_activity(since=since, limit=limit)
    latest_sequence = events[-1]["sequence"] if events else since
    return {
        "events": events,
        "latest_sequence": latest_sequence,
    }


@router.get("/documents/{document_id}/status")
async def document_status(document_id: uuid.UUID, session: DbSession) -> dict:
    """Return ingestion status for a document so the UI can show task progress."""
    start = time.perf_counter()
    logger.info("document_status_requested", document_id=str(document_id))
    doc = await crud.get_document(session, document_id)
    if not doc:
        logger.warning("document_status_not_found", document_id=str(document_id))
        raise HTTPException(status_code=404, detail="Document not found")
    chunk_count = await crud.count_chunks_by_document(session, document_id)
    logger.info(
        "document_status_returned",
        document_id=str(document_id),
        status=doc.status,
        chunk_count=chunk_count,
        source_type=doc.source_type,
        source_id=doc.source_id,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    return {
        "document_id": str(doc.id),
        "tenant_id": str(doc.tenant_id),
        "source_type": doc.source_type,
        "source_id": doc.source_id,
        "title": doc.title,
        "status": doc.status,
        "chunk_count": chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.get("/health/db")
async def health_db(session: DbSession) -> dict:
    """Health check with DB connectivity."""
    start = time.perf_counter()
    await session.execute(text("SELECT 1"))
    logger.info("db_health_check", duration_ms=round((time.perf_counter() - start) * 1000, 2))
    return {"status": "healthy", "database": "connected"}


@router.get("/ollama/ping")
async def ollama_ping() -> dict:
    """Probe OLLAMA_BASE_URL from the API process (same as /query uses). Debugging 404s."""
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    checks: dict = {}
    logger.info("ollama_ping_started", base_url=base)
    async with httpx.AsyncClient(timeout=8.0) as client:
        for path, method in (
            ("/api/tags", "GET"),
            ("/api/version", "GET"),
            ("/v1/models", "GET"),
        ):
            url = f"{base}{path}"
            start = time.perf_counter()
            try:
                r = await client.request(method, url)
                checks[path] = {"status_code": r.status_code, "content_type": r.headers.get("content-type", "")}
                logger.info(
                    "ollama_ping_check_complete",
                    path=path,
                    status_code=r.status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                )
            except Exception as e:
                checks[path] = {"error": str(e)}
                logger.warning("ollama_ping_check_failed", path=path, error=str(e))
    return {"ollama_base_url": base, "checks": checks}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: uuid.UUID, session: DbSession) -> dict:
    """Delete a document and all its chunks (e.g. stuck ``queued`` rows)."""
    logger.info("document_delete_requested", document_id=str(document_id))
    deleted = await crud.delete_document_by_id(session, document_id)
    if not deleted:
        logger.warning("document_delete_not_found", document_id=str(document_id))
        raise HTTPException(status_code=404, detail="Document not found")
    logger.info("document_deleted", document_id=str(document_id))
    return {"status": "deleted", "document_id": str(document_id)}
