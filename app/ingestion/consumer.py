"""Kafka consumer worker for ingestion."""
import asyncio
import json
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
    data = json.loads(msg_value)
    document_id = uuid.UUID(data["document_id"])
    tenant_id = uuid.UUID(data["tenant_id"])
    source_type = data["source_type"]
    source_id = data["source_id"]
    payload = data.get("payload", {})

    async with session_factory() as session:
        try:
            await run_pipeline(session, document_id, tenant_id, source_type, source_id, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def run_consumer() -> None:
    """Run Kafka consumer loop."""
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
            try:
                await process_message(session_factory, msg.value.decode("utf-8"))
                await consumer.commit()
            except Exception as e:
                logger.exception("consumer_message_failed", error=str(e), offset=msg.offset)
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
