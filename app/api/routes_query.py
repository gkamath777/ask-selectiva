"""Query routes for RAG."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.session import DbSession
from app.rag.service import RAGResponse, query

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    """RAG query request."""

    tenant_id: uuid.UUID
    question: str = Field(..., min_length=1, max_length=5000)


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
    result: RAGResponse = await query(
        session=session,
        tenant_id=req.tenant_id,
        question=req.question,
        top_k=5,
    )
    return QueryResponse(
        answer=result.answer,
        citations=result.citations,
        model_used=result.model_used,
    )
