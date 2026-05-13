"""Multipart uploads (PDF) for ingestion."""
import hashlib
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.logging import get_logger
from app.db import crud
from app.db.session import DbSession
from app.ingestion.pdf_extract import extract_text_from_pdf
from app.kafka.ingest_publish import publish_ingest_for_document

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

MAX_PDF_BYTES = 50 * 1024 * 1024


def _default_source_id(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = re.sub(r"[^\w\-.]+", "_", stem).strip("_")[:120]
    return cleaned or "pdf-upload"


@router.post("/pdf")
async def upload_pdf(
    session: DbSession,
    tenant_id: uuid.UUID = Form(..., description="Same tenant as queries"),
    file: UploadFile = File(..., description="PDF file"),
    title: str | None = Form(None),
    source_id: str | None = Form(
        None,
        description="Stable id for re-ingest / upsert; defaults from filename",
    ),
) -> dict:
    """
    Upload a PDF: text is extracted, document is queued like /webhooks/ingest.
    Image-only or scanned PDFs may return no text (400).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a .pdf")

    raw = await file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"PDF too large (max {MAX_PDF_BYTES // (1024 * 1024)} MB)",
        )

    try:
        text = extract_text_from_pdf(raw)
    except Exception as e:
        logger.warning("pdf_parse_failed", error=str(e), filename=file.filename)
        raise HTTPException(
            status_code=400,
            detail="Could not read PDF. File may be corrupted or password-protected.",
        ) from e

    if not text:
        raise HTTPException(
            status_code=400,
            detail="No extractable text in this PDF (try OCR for scanned documents).",
        )

    sid = (source_id or _default_source_id(file.filename)).strip() or "pdf-upload"
    display_title = (title or file.filename).strip() or sid
    content_hash = hashlib.sha256(raw).hexdigest()

    payload = {
        "tenant_id": str(tenant_id),
        "source_type": "upload",
        "source_id": sid,
        "title": display_title,
        "uri": None,
        "content": text,
    }

    doc = await crud.upsert_document(
        session,
        tenant_id=tenant_id,
        source_type="upload",
        source_id=sid,
        title=display_title,
        uri=None,
        content_hash=content_hash,
        status="queued",
    )
    await session.commit()

    await publish_ingest_for_document(
        session,
        document_id=doc.id,
        tenant_id=tenant_id,
        source_type="upload",
        source_id=sid,
        payload=payload,
    )

    logger.info(
        "pdf_upload_accepted",
        document_id=str(doc.id),
        tenant_id=str(tenant_id),
        source_id=sid,
    )

    return {
        "status": "queued",
        "document_id": str(doc.id),
        "message": "PDF queued for ingestion",
        "chars_extracted": len(text),
    }
