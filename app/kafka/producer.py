"""Kafka producer for ingestion events."""
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.kafka.topics import KNOWLEDGE_INGEST_REQUESTS

logger = get_logger(__name__)

_settings = get_settings()
_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    """Get or create Kafka producer."""
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=_settings.kafka_bootstrap_servers.split(","),
            value_serializer=lambda v: v.encode("utf-8") if isinstance(v, str) else v,
        )
        await _producer.start()
        logger.info("kafka_producer_started", servers=_settings.kafka_bootstrap_servers)
    return _producer


async def shutdown_producer() -> None:
    """Shutdown Kafka producer."""
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
        logger.info("kafka_producer_stopped")


async def publish_ingest_request(
    document_id: str,
    tenant_id: str,
    source_type: str,
    source_id: str,
    payload: dict[str, Any],
) -> None:
    """Publish ingest request to Kafka."""
    import json

    producer = await get_producer()
    msg = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "source_type": source_type,
        "source_id": source_id,
        "payload": payload,
    }
    msg_str = json.dumps(msg)
    try:
        await producer.send_and_wait(
            KNOWLEDGE_INGEST_REQUESTS,
            value=msg_str,
            key=document_id.encode("utf-8"),
        )
        logger.info(
            "ingest_request_published",
            document_id=document_id,
            tenant_id=tenant_id,
            source_type=source_type,
        )
    except KafkaError as e:
        logger.error("kafka_publish_failed", error=str(e), document_id=document_id)
        raise
