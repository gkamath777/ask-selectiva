"""Admin routes: health, etc."""
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.config import get_settings
from app.db import crud
from app.db.session import DbSession

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def health() -> dict:
    """Health check - no DB dependency."""
    return {"status": "healthy", "service": "ask-selectiva"}


@router.get("/health/db")
async def health_db(session: DbSession) -> dict:
    """Health check with DB connectivity."""
    await session.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}


@router.get("/ollama/ping")
async def ollama_ping() -> dict:
    """Probe OLLAMA_BASE_URL from the API process (same as /query uses). Debugging 404s."""
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    checks: dict = {}
    async with httpx.AsyncClient(timeout=8.0) as client:
        for path, method in (
            ("/api/tags", "GET"),
            ("/api/version", "GET"),
            ("/v1/models", "GET"),
        ):
            url = f"{base}{path}"
            try:
                r = await client.request(method, url)
                checks[path] = {"status_code": r.status_code, "content_type": r.headers.get("content-type", "")}
            except Exception as e:
                checks[path] = {"error": str(e)}
    return {"ollama_base_url": base, "checks": checks}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: uuid.UUID, session: DbSession) -> dict:
    """Delete a document and all its chunks (e.g. stuck ``queued`` rows)."""
    deleted = await crud.delete_document_by_id(session, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": str(document_id)}
