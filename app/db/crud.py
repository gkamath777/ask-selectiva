"""CRUD operations for documents and chunks."""
import uuid
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Chunk, Document, GoogleDriveChannelState

logger = get_logger(__name__)


async def upsert_document(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: str,
    title: Optional[str] = None,
    uri: Optional[str] = None,
    content_hash: Optional[str] = None,
    status: str = "queued",
) -> Document:
    """Upsert document by tenant + source_type + source_id. Idempotent."""
    result = await session.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_type == source_type,
            Document.source_id == source_id,
        )
    )
    doc = result.scalar_one_or_none()

    if doc:
        logger.info(
            "document_upsert_existing",
            document_id=str(doc.id),
            tenant_id=str(tenant_id),
            source_type=source_type,
            source_id=source_id,
            status=status,
        )
        doc.title = title or doc.title
        doc.uri = uri or doc.uri
        doc.content_hash = content_hash or doc.content_hash
        doc.status = status
        await session.flush()
        return doc

    doc = Document(
        tenant_id=tenant_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        uri=uri,
        content_hash=content_hash,
        status=status,
    )
    session.add(doc)
    await session.flush()
    logger.info(
        "document_upsert_created",
        document_id=str(doc.id),
        tenant_id=str(tenant_id),
        source_type=source_type,
        source_id=source_id,
        status=status,
    )
    return doc


async def get_document_by_tenant_source(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    source_type: str,
    source_id: str,
) -> Optional[Document]:
    """Lookup document by tenant + source (e.g. google_drive file id)."""
    result = await session.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_type == source_type,
            Document.source_id == source_id,
        )
    )
    return result.scalar_one_or_none()


async def get_document(
    session: AsyncSession,
    document_id: uuid.UUID,
) -> Optional[Document]:
    """Get document by ID."""
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def count_chunks_by_document(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Count chunks stored for a document."""
    result = await session.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id))
    return int(result.scalar_one())


async def delete_document_by_id(session: AsyncSession, document_id: uuid.UUID) -> bool:
    """Remove document and its chunks. Returns False if document did not exist."""
    doc = await get_document(session, document_id)
    if not doc:
        logger.info("document_delete_skipped_missing", document_id=str(document_id))
        return False
    await delete_chunks_by_document(session, document_id)
    await session.execute(delete(Document).where(Document.id == document_id))
    await session.flush()
    logger.info("document_delete_flushed", document_id=str(document_id))
    return True


async def update_document_status(
    session: AsyncSession,
    document_id: uuid.UUID,
    status: str,
) -> None:
    """Update document status."""
    await session.execute(update(Document).where(Document.id == document_id).values(status=status))
    await session.flush()
    logger.info("document_status_updated", document_id=str(document_id), status=status)


async def delete_chunks_by_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Delete all chunks for a document."""
    await session.execute(Chunk.__table__.delete().where(Chunk.document_id == document_id))
    await session.flush()
    logger.info("document_chunks_deleted", document_id=str(document_id))


async def insert_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    chunks: list[tuple[str, list[float], Optional[dict]]],
) -> None:
    """Insert chunks with embeddings."""
    logger.info("document_chunks_insert_started", document_id=str(document_id), chunk_count=len(chunks))
    for idx, (text, embedding, metadata) in enumerate(chunks):
        chunk = Chunk(
            document_id=document_id,
            tenant_id=tenant_id,
            chunk_index=idx,
            text=text,
            embedding=embedding,
            doc_metadata=metadata,
        )
        session.add(chunk)
    await session.flush()
    logger.info("document_chunks_insert_finished", document_id=str(document_id), chunk_count=len(chunks))


async def get_drive_channel_state(session: AsyncSession) -> Optional[GoogleDriveChannelState]:
    """Singleton row for Drive push channel verification."""
    result = await session.execute(select(GoogleDriveChannelState).where(GoogleDriveChannelState.id == 1))
    return result.scalar_one_or_none()


async def upsert_drive_channel_state(
    session: AsyncSession,
    channel_id: str,
    resource_id: Optional[str],
    expiration_ms: Optional[int],
) -> None:
    row = await get_drive_channel_state(session)
    if row:
        logger.info("drive_channel_state_updated", channel_id=channel_id, expiration_ms=expiration_ms)
        row.channel_id = channel_id
        row.resource_id = resource_id
        row.expiration_ms = expiration_ms
    else:
        logger.info("drive_channel_state_created", channel_id=channel_id, expiration_ms=expiration_ms)
        session.add(
            GoogleDriveChannelState(
                id=1,
                channel_id=channel_id,
                resource_id=resource_id,
                expiration_ms=expiration_ms,
            )
        )
    await session.flush()
