"""Kafka consumer worker for ingestion."""
import asyncio
import json
import time
import uuid

from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Base
from app.ingestion.pipeline import run_pipeline
from app.kafka.topics import KNOWLEDGE_INGEST_REQUESTS

logger = get_logger(__name__)


async def process_message(session_factory: async_sessionmaker[AsyncSession], msg_value: str) -> None:
    """Process a single ingest message."""
    start = time.perf_counter()
    data = json.loads(msg_value)
    document_id = uuid.UUID(data["document_id"])
    tenant_id = uuid.UUID(data["tenant_id"])
    source_type = data["source_type"]
    source_id = data["source_id"]
    payload = data.get("payload", {})
    logger.info(
        "consumer_message_processing_started",
        document_id=str(document_id),
        tenant_id=str(tenant_id),
        source_type=source_type,
        source_id=source_id,
        payload_keys=sorted(payload.keys()) if isinstance(payload, dict) else [],
    )

    async with session_factory() as session:
        try:
            await run_pipeline(session, document_id, tenant_id, source_type, source_id, payload)
            await session.commit()
            logger.info(
                "consumer_message_processing_finished",
                document_id=str(document_id),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "consumer_message_processing_rolled_back",
                document_id=str(document_id),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise


async def run_consumer() -> None:
    """Run Kafka consumer loop."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    logger.info(
        "consumer_booting",
        topic=KNOWLEDGE_INGEST_REQUESTS,
        kafka_bootstrap_servers=settings.kafka_bootstrap_servers,
        max_poll_interval_ms=settings.kafka_max_poll_interval_ms,
        log_format=settings.log_format,
    )

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    if settings.create_db_on_startup:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("consumer_db_init_finished", create_db_on_startup=True)
    else:
        logger.info("consumer_db_init_skipped", create_db_on_startup=False)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    consumer = AIOKafkaConsumer(
        KNOWLEDGE_INGEST_REQUESTS,
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        group_id="ingestion-workers",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        max_poll_interval_ms=settings.kafka_max_poll_interval_ms,
    )
    await consumer.start()
    logger.info("consumer_started", topic=KNOWLEDGE_INGEST_REQUESTS)

    try:
        async for msg in consumer:
            logger.info(
                "consumer_message_received",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                key=msg.key.decode("utf-8") if msg.key else None,
            )
            try:
                await process_message(session_factory, msg.value.decode("utf-8"))
                await consumer.commit()
                logger.info(
                    "consumer_message_committed",
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                )
            except Exception as e:
                logger.exception(
                    "consumer_message_failed",
                    error=str(e),
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                )
                # Don't commit - will retry
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("consumer_stopped")


def main() -> None:
    """Entry point."""
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
