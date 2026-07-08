"""Query routes for RAG."""
import time
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.session import DbSession
from app.rag.service import RAGResponse, query

logger = get_logger(__name__)

router = APIRouter(prefix="/query", tags=["query"], dependencies=[Depends(require_api_key)])


class ChatMessage(BaseModel):
    """Recent chat turn used to resolve follow-up questions."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=5000)


class QueryRequest(BaseModel):
    """RAG query request."""

    tenant_id: uuid.UUID
    question: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(5, ge=1, le=10)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


class QueryResponse(BaseModel):
    """RAG query response."""

    answer: str
    citations: list[dict[str, str | None]]
    model_used: str


@router.post("", response_model=QueryResponse)
async def post_query(
    req: QueryRequest,
    session: DbSession,
) -> QueryResponse:
    """
    RAG query:
    1. Embed question
    2. Vector search (top_k=5)
    3. Build prompt
    4. Send to Ollama
    5. Return answer + citations
    """
    settings = get_settings()
    top_k = min(req.top_k, settings.max_query_top_k)
    start = time.perf_counter()
    logger.info(
        "query_request_received",
        tenant_id=str(req.tenant_id),
        question_length=len(req.question),
        top_k=top_k,
        history_count=len(req.history),
    )
    result: RAGResponse = await query(
        session=session,
        tenant_id=req.tenant_id,
        question=req.question,
        top_k=top_k,
        history=[m.model_dump() for m in req.history],
    )
    logger.info(
        "query_request_completed",
        tenant_id=str(req.tenant_id),
        model_used=result.model_used,
        citation_count=len(result.citations),
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    return QueryResponse(
        answer=result.answer,
        citations=result.citations,
        model_used=result.model_used,
    )
