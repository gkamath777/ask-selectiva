"""RAG query service: embed → search → prompt → generate."""
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.vector_search import SearchResult, vector_search
from app.embeddings.local_embeddings import embed
from app.llm.ollama_client import generate
from app.llm.router import select_model
from app.rag.prompt_builder import build_rag_prompt
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RAGResponse:
    """RAG query response with answer and citations."""

    answer: str
    citations: list[dict[str, Optional[str]]]
    model_used: str


async def query(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    question: str,
    top_k: int = 5,
) -> RAGResponse:
    """
    RAG query flow:
    1. Embed question
    2. Vector search (top_k)
    3. Build prompt
    4. Send to Ollama
    5. Return answer + citations
    """
    # 1. Embed
    query_embeddings = embed(question)
    query_embedding = query_embeddings[0]

    # 2. Vector search
    results = await vector_search(session, tenant_id, query_embedding, top_k=top_k)

    # 3. Build prompt
    prompt = build_rag_prompt(results, question)

    # 4. Select model and generate
    model = select_model(question)
    answer = await generate(prompt=prompt, model=model)

    # 5. Build citations
    citations = [
        {
            "title": r.document_title,
            "uri": r.document_uri,
            "source_type": r.source_type,
            "source_id": r.source_id,
        }
        for r in results
    ]

    logger.info(
        "rag_query_complete",
        tenant_id=str(tenant_id),
        model_used=model,
        result_count=len(results),
    )

    return RAGResponse(answer=answer, citations=citations, model_used=model)
