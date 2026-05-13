"""Ingestion pipeline: fetch → parse → chunk → embed → store."""
import asyncio
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
    try:
        # 1. Fetch content
        content = await fetch_content(source_type, source_id, payload)
        if not content:
            await crud.update_document_status(session, document_id, "failed")
            logger.warning("pipeline_no_content", document_id=str(document_id))
            return

        # 2. Parse (passthrough - add PDF/HTML parsers later)
        text = content

        # 3. Chunk
        chunks = chunk_text(text, chunk_size=1000, overlap=200)
        if not chunks:
            await crud.update_document_status(session, document_id, "failed")
            logger.warning("pipeline_no_chunks", document_id=str(document_id))
            return

        # 4. Embed (CPU-bound; run off the asyncio loop so Kafka heartbeats still fire)
        embeddings = await asyncio.to_thread(embed_text, chunks)

        # 5. Delete existing chunks, insert new
        await crud.delete_chunks_by_document(session, document_id)
        chunk_data = [(c, emb, None) for c, emb in zip(chunks, embeddings)]
        await crud.insert_chunks(session, document_id, tenant_id, chunk_data)

        # 6. Mark ready
        await crud.update_document_status(session, document_id, "ready")

        logger.info(
            "pipeline_complete",
            document_id=str(document_id),
            chunk_count=len(chunks),
        )
    except Exception as e:
        logger.exception("pipeline_failed", document_id=str(document_id), error=str(e))
        await crud.update_document_status(session, document_id, "failed")
        raise
