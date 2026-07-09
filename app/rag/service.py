"""RAG query service: embed → search → prompt → generate."""
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.vector_search import SearchResult, vector_search
from app.embeddings.local_embeddings import embed
from app.core.config import get_settings
from app.llm.ollama_client import generate as generate_ollama
from app.llm.openai_client import generate as generate_openai
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
    llm_provider: str = "ollama",
) -> RAGResponse:
    """
    RAG query flow:
    1. Embed question
    2. Vector search (top_k)
    3. Build prompt
    4. Send to Ollama
    5. Return answer + citations
    """
    started = time.perf_counter()
    history_count = len(history or [])
    history_decision = _decide_history_use(question, history or [])
    use_history = history_decision == "use"
    effective_history = history if use_history else []
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
    retrieval_question = _build_retrieval_question(question, effective_history or [])
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
    provider = _normalize_llm_provider(llm_provider)
    model = select_model(question) if provider == "ollama" else get_settings().openai_model
    phase_started = time.perf_counter()
    if provider == "openai":
        answer = await generate_openai(prompt=prompt)
    else:
        answer = await generate_ollama(prompt=prompt, model=model)
    logger.info(
        "rag_query_generation_complete",
        tenant_id=str(tenant_id),
        llm_provider=provider,
        model_used=model,
        answer_chars=len(answer),
        duration_ms=round((time.perf_counter() - phase_started) * 1000, 2),
    )

    # 5. Build citations
    citations = _build_unique_citations(results)

    logger.info(
        "rag_query_complete",
        tenant_id=str(tenant_id),
        llm_provider=provider,
        model_used=model,
        result_count=len(results),
        citation_count=len(citations),
        raw_citation_count=len(results),
        history_count=history_count,
        history_decision=history_decision,
        use_history=use_history,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )

    return RAGResponse(answer=answer, citations=citations, model_used=model)


def _normalize_llm_provider(llm_provider: str) -> str:
    provider = (llm_provider or "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        logger.warning("unsupported_llm_provider", llm_provider=llm_provider)
        return "ollama"
    return provider


def _decide_history_use(question: str, history: list[dict[str, str]]) -> str:
    """Decide whether to use, ignore, or clarify previous chat context."""
    if not history:
        return "ignore"

    q = " ".join(question.lower().strip().split())
    if not q:
        return "ignore"

    explicit_references = (
        "previous",
        "earlier",
        "last answer",
        "your answer",
        "your response",
        "above",
        "as mentioned",
        "as you said",
        "that answer",
        "same",
        "continue",
        "carry on",
        "follow up",
        "follow-up",
        "point ",
        "section ",
    )
    if any(term in q for term in explicit_references):
        return "use"

    followup_starts = (
        "what about",
        "how about",
        "and ",
        "also ",
        "then ",
        "so ",
        "but ",
        "why ",
        "expand",
        "elaborate",
        "rewrite",
        "summarize",
        "make it",
        "make this",
        "convert it",
        "can you add",
        "add more",
    )
    if any(q.startswith(term) for term in followup_starts):
        return "use"

    reference_words = {"it", "that", "this", "they", "them", "those", "these", "there"}
    words = {word.strip(".,?!:;()[]{}\"'") for word in q.split()}
    if len(q) <= 120 and words & reference_words:
        return "clarify"

    return "ignore"


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

    logger.info(
        "rag_citations_compacted",
        raw_citation_count=len(results),
        citation_count=len(citations),
        omitted_count=max(0, len(results) - len(citations)),
        max_citations=max_citations,
    )
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
