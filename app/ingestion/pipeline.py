"""Ingestion pipeline: fetch → parse → chunk → embed → store."""
import asyncio
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db import crud
from app.embeddings.local_embeddings import embed as embed_text
from app.ingestion.chunking import chunk_text
from app.ingestion.connectors import fetch_content

logger = get_logger(__name__)


async def run_pipeline(
    session: AsyncSession,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: str,
    payload: dict,
) -> None:
    """
    Run full ingestion pipeline:
    1. Fetch content (stub)
    2. Parse text (passthrough for now)
    3. Chunk (1000 char, 200 overlap)
    4. Embed
    5. Store chunks
    6. Mark document ready
    """
    started = time.perf_counter()
    logger.info(
        "pipeline_started",
        document_id=str(document_id),
        tenant_id=str(tenant_id),
        source_type=source_type,
        source_id=source_id,
    )
    try:
        # 1. Fetch content
        phase_started = time.perf_counter()
        content = await fetch_content(source_type, source_id, payload)
        if not content:
            await crud.update_document_status(session, document_id, "failed")
            logger.warning(
                "pipeline_no_content",
                document_id=str(document_id),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return
        logger.info(
            "pipeline_fetch_complete",
            document_id=str(document_id),
            content_chars=len(content),
            duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
        )

        # 2. Parse (passthrough - add PDF/HTML parsers later)
        text = content

        # 3. Chunk
        phase_started = time.perf_counter()
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        if not chunks:
            await crud.update_document_status(session, document_id, "failed")
            logger.warning(
                "pipeline_no_chunks",
                document_id=str(document_id),
                text_chars=len(text),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return
        logger.info(
            "pipeline_chunking_complete",
            document_id=str(document_id),
            text_chars=len(text),
            chunk_count=len(chunks),
            duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
        )

        # 4. Embed (CPU-bound; run off the asyncio loop so Kafka heartbeats still fire)
        phase_started = time.perf_counter()
        embeddings = await asyncio.to_thread(embed_text, chunks)
        logger.info(
            "pipeline_embedding_complete",
            document_id=str(document_id),
            chunk_count=len(chunks),
            embedding_count=len(embeddings),
            duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
        )

        # 5. Delete existing chunks, insert new
        phase_started = time.perf_counter()
        await crud.delete_chunks_by_document(session, document_id)
        chunk_data = [(c, emb, None) for c, emb in zip(chunks, embeddings)]
        await crud.insert_chunks(session, document_id, tenant_id, chunk_data)
        logger.info(
            "pipeline_store_complete",
            document_id=str(document_id),
            chunk_count=len(chunk_data),
            duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
        )

        # 6. Mark ready
        await crud.update_document_status(session, document_id, "ready")

        logger.info(
            "pipeline_complete",
            document_id=str(document_id),
            chunk_count=len(chunks),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception as e:
        logger.exception(
            "pipeline_failed",
            document_id=str(document_id),
            source_type=source_type,
            source_id=source_id,
            error=str(e),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        await crud.update_document_status(session, document_id, "failed")
        raise
