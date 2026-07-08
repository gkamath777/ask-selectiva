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
    history: list[dict[str, str]] | None = None,
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
    retrieval_question = _build_retrieval_question(question, history or [])
    query_embeddings = embed(retrieval_question)
    query_embedding = query_embeddings[0]

    # 2. Vector search
    results = await vector_search(session, tenant_id, query_embedding, top_k=top_k)

    # 3. Build prompt
    prompt = build_rag_prompt(results, question, history=history)

    # 4. Select model and generate
    model = select_model(question)
    answer = await generate(prompt=prompt, model=model)

    # 5. Build citations
    citations = _build_unique_citations(results)

    logger.info(
        "rag_query_complete",
        tenant_id=str(tenant_id),
        model_used=model,
        result_count=len(results),
        history_count=len(history or []),
    )

    return RAGResponse(answer=answer, citations=citations, model_used=model)


def _build_unique_citations(
    results: list[SearchResult],
    max_citations: int = 2,
) -> list[dict[str, Optional[str]]]:
    """Return a compact citation list without repeating the same file/source."""
    citations = []
    seen = set()

    for r in results:
        citation = {
            "title": r.document_title,
            "uri": r.document_uri,
            "source_type": r.source_type,
            "source_id": r.source_id,
        }
        key = _citation_key(citation)
        if key in seen:
            continue
        seen.add(key)
        citations.append(citation)
        if len(citations) >= max_citations:
            break

    return citations


def _citation_key(citation: dict[str, Optional[str]]) -> str:
    """Group repeated chunks from the same uploaded file or external URI."""
    for value in (citation.get("title"), citation.get("uri"), citation.get("source_id")):
        if value:
            cleaned = value.rstrip("/").split("/")[-1].split("?")[0].strip().lower()
            if cleaned:
                return cleaned
    return f"{citation.get('source_type') or ''}:{citation.get('source_id') or ''}".lower()


def _build_retrieval_question(question: str, history: list[dict[str, str]]) -> str:
    """Add recent turns to retrieval text so short follow-ups search the right concepts."""
    recent_lines = []
    for item in history[-6:]:
        role = item.get("role", "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = item.get("content", "").strip()
        if not content:
            continue
        if len(content) > 700:
            content = content[:700].rstrip() + "..."
        recent_lines.append(f"{role}: {content}")

    if not recent_lines:
        return question

    return (
        f"Current follow-up question:\n{question}\n\n"
        "Relevant recent conversation for resolving the follow-up:\n"
        + "\n".join(recent_lines)
    )
