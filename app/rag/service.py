"""RAG query service: embed → search → prompt → generate."""
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.vector_search import vector_search
from app.embeddings.local_embeddings import embed
from app.llm.service import generate_answer
from app.rag.citations import build_unique_citations
from app.rag.history import build_retrieval_question, decide_history_use, normalize_history
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
    llm_provider: str = "ollama",
) -> RAGResponse:
    """
    RAG query flow:
    1. Embed question
    2. Vector search (top_k)
    3. Build prompt
    4. Generate with the selected LLM provider
    5. Return answer + citations
    """
    started = time.perf_counter()
    chat_history = normalize_history(history)
    history_count = len(chat_history)
    history_decision = decide_history_use(question, chat_history)
    use_history = history_decision == "use"
    effective_history = chat_history if use_history else []
    logger.info(
        "rag_query_started",
        tenant_id=str(tenant_id),
        question_length=len(question),
        top_k=top_k,
        history_count=history_count,
        history_decision=history_decision,
        llm_provider=llm_provider,
    )

    if history_decision == "clarify":
        logger.info(
            "rag_query_clarification_requested",
            tenant_id=str(tenant_id),
            question_length=len(question),
            history_count=history_count,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return RAGResponse(
            answer=(
                "Do you want me to answer this as a follow-up to the previous conversation, "
                "or as a new standalone question?"
            ),
            citations=[],
            model_used="clarification",
        )

    # 1. Embed
    phase_started = time.perf_counter()
    retrieval_question = build_retrieval_question(question, effective_history)
    query_embeddings = embed(retrieval_question)
    query_embedding = query_embeddings[0]
    logger.info(
        "rag_query_embedding_complete",
        tenant_id=str(tenant_id),
        retrieval_question_length=len(retrieval_question),
        embedding_dimensions=len(query_embedding),
        duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
    )

    # 2. Vector search
    phase_started = time.perf_counter()
    results = await vector_search(session, tenant_id, query_embedding, top_k=top_k)
    logger.info(
        "rag_query_vector_search_complete",
        tenant_id=str(tenant_id),
        result_count=len(results),
        top_k=top_k,
        duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
    )

    # 3. Build prompt
    phase_started = time.perf_counter()
    prompt = build_rag_prompt(results, question, history=effective_history)
    logger.info(
        "rag_query_prompt_built",
        tenant_id=str(tenant_id),
        prompt_chars=len(prompt),
        context_result_count=len(results),
        history_count=len(effective_history or []),
        use_history=use_history,
        duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
    )

    # 4. Select model and generate
    generation = await generate_answer(prompt=prompt, question=question, llm_provider=llm_provider)
    logger.info(
        "rag_query_generation_complete",
        tenant_id=str(tenant_id),
        llm_provider=generation.provider,
        model_used=generation.model,
        answer_chars=len(generation.answer),
        duration_ms=generation.duration_ms,
    )

    # 5. Build citations
    citations = build_unique_citations(results)

    logger.info(
        "rag_query_complete",
        tenant_id=str(tenant_id),
        llm_provider=generation.provider,
        model_used=generation.model,
        result_count=len(results),
        citation_count=len(citations),
        raw_citation_count=len(results),
        history_count=history_count,
        history_decision=history_decision,
        use_history=use_history,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )

    return RAGResponse(
        answer=generation.answer,
        citations=citations,
        model_used=generation.model,
    )
