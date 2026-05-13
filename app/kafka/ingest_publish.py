"""Publish ingest messages to Kafka with consistent failure handling."""
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db import crud
from app.kafka.producer import publish_ingest_request

logger = get_logger(__name__)


async def publish_ingest_for_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: str,
    payload: dict[str, Any],
    translate_to_http: bool = True,
) -> bool:
    """
    Send document to Kafka for the ingestion worker.
    On failure: marks document ``failed``, commits, then raises HTTP 503 if
    ``translate_to_http`` else returns False.
    """
    try:
        await publish_ingest_request(
            document_id=str(document_id),
            tenant_id=str(tenant_id),
            source_type=source_type,
            source_id=source_id,
            payload=payload,
        )
        return True
    except Exception as e:
        logger.exception(
            "ingest_kafka_publish_failed",
            document_id=str(document_id),
            error=str(e),
        )
        await crud.update_document_status(session, document_id, "failed")
        await session.commit()
        if translate_to_http:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Ingestion queue (Kafka) is unavailable. "
                    "With Docker: `docker compose up -d` and wait until Kafka is up. "
                    "Locally: set KAFKA_BOOTSTRAP_SERVERS and start a broker. "
                    f"Details: {e!s}"
                ),
            ) from e
        return False
