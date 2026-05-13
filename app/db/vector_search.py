"""Vector similarity search using pgvector."""
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SearchResult:
    """Single search result with chunk text and document metadata for citations."""

    chunk_text: str
    document_title: str | None
    document_uri: str | None
    source_type: str
    source_id: str


async def vector_search(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[SearchResult]:
    """
    Search chunks by vector similarity within tenant.
    Returns results ordered by similarity (cosine distance).
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    stmt = text("""
        SELECT c.text, d.title, d.uri, d.source_type, d.source_id
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.tenant_id = :tenant_id
          AND d.status = 'ready'
          AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """)

    result = await session.execute(
        stmt,
        {"tenant_id": str(tenant_id), "embedding": embedding_str, "top_k": top_k},
    )
    rows = result.fetchall()

    return [
        SearchResult(
            chunk_text=row.text,
            document_title=row.title,
            document_uri=row.uri,
            source_type=row.source_type,
            source_id=row.source_id,
        )
        for row in rows
    ]
