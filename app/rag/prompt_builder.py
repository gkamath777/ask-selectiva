"""RAG prompt construction."""
from app.db.vector_search import SearchResult
from app.rag.history import ChatTurn, format_history

SYSTEM_INSTRUCTION = """You are a helpful assistant. Use the provided context as your source of truth.
You may synthesize, summarize, draft, rewrite, structure, or create new deliverables such as proposals when the user asks for them, but factual claims must be grounded in the context.
If required details, reference numbers, IDs, dates, amounts, entities, or source data are missing or ambiguous, ask a concise follow-up question instead of assuming or inventing facts.
If a useful partial answer is possible, provide only the grounded part and clearly ask for the missing detail needed to finish.
If the context is not relevant to the request, say so clearly.
Cite sources when possible.
Use conversation history only when it is provided. When no history is provided, treat the question as standalone.
For factual claims about the knowledge base or outside world, use the retrieved context as the source of truth."""


def build_rag_prompt(
    context_results: list[SearchResult],
    question: str,
    history: list[ChatTurn] | None = None,
) -> str:
    """Build prompt with system instruction, context, and question."""
    context_parts = []
    for i, r in enumerate(context_results, 1):
        source = r.document_uri or r.document_title or f"{r.source_type}:{r.source_id}"
        context_parts.append(f"[Source {i} - {source}]\n{r.chunk_text}")

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "(No relevant context found.)"
    history_block = format_history(history or [])

    return f"""{SYSTEM_INSTRUCTION}

## Conversation History

{history_block}

## Context

{context_block}

## Current Question

If conversation history is present, use it only to resolve follow-up references such as "that", "it", "the previous answer", or "point 2".
If conversation history is not present, answer the current question as a standalone request.
Before producing a final answer, check whether the request depends on missing or ambiguous details such as reference numbers, IDs, dates, amounts, entities, or source data. If it does, ask a concise follow-up question and do not guess.

{question}

## Answer

"""
