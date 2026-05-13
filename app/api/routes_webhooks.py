"""Webhook routes for ingestion."""
import hashlib
import hmac
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import crud
from app.db.session import DbSession
from app.kafka.ingest_publish import publish_ingest_for_document

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookPayload(BaseModel):
    """Webhook ingest request."""

    tenant_id: uuid.UUID
    source_type: str = Field(..., description="e.g. drive, jira, email")
    source_id: str = Field(..., description="Unique ID in source system")
    title: Optional[str] = None
    uri: Optional[str] = None
    content: Optional[str] = None
    body: Optional[str] = None
    text: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


def _compute_content_hash(body: bytes) -> str:
    """Compute SHA256 hash of request body."""
    return hashlib.sha256(body).hexdigest()


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/ingest")
async def webhook_ingest(
    request: Request,
    session: DbSession,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_hmac_sha256: str | None = Header(None, alias="X-HMAC-SHA256"),
) -> dict[str, Any]:
    """
    Webhook ingestion:
    1. Validate HMAC (if WEBHOOK_SECRET set)
    2. Upsert document (status=queued)
    3. Publish to Kafka
    4. Return immediately
    """
    body = await request.body()
    settings = get_settings()

    if settings.webhook_secret:
        sig = x_signature or x_hmac_sha256
        if not sig:
            raise HTTPException(status_code=401, detail="Missing signature header")
        if not _verify_hmac(body, sig, settings.webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    payload = WebhookPayload(**data)
    content_hash = _compute_content_hash(body)

    # Build payload for consumer (mode="json" converts UUIDs to str for Kafka)
    consumer_payload = payload.model_dump(mode="json", exclude_none=True)

    # Upsert document
    doc = await crud.upsert_document(
        session,
        tenant_id=payload.tenant_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        title=payload.title,
        uri=payload.uri,
        content_hash=content_hash,
        status="queued",
    )
    await session.commit()  # Commit before Kafka so consumer finds document

    await publish_ingest_for_document(
        session,
        document_id=doc.id,
        tenant_id=payload.tenant_id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        payload=consumer_payload,
    )

    logger.info(
        "webhook_ingest_accepted",
        document_id=str(doc.id),
        tenant_id=str(payload.tenant_id),
        source_type=payload.source_type,
    )

    return {
        "status": "queued",
        "document_id": str(doc.id),
        "message": "Document queued for ingestion",
    }
