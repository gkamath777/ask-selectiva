"""RAG prompt construction."""
from app.db.vector_search import SearchResult

SYSTEM_INSTRUCTION = """You are a helpful assistant. Use the provided context as your source of truth.
You may synthesize, summarize, draft, rewrite, structure, or create new deliverables such as proposals when the user asks for them, but factual claims must be grounded in the context.
If required details are missing from the context, include a clearly labeled assumption, placeholder, or open question instead of refusing or inventing facts.
If the context is not relevant to the request, say so clearly.
Cite sources when possible."""


def build_rag_prompt(context_results: list[SearchResult], question: str) -> str:
    """Build prompt with system instruction, context, and question."""
    context_parts = []
    for i, r in enumerate(context_results, 1):
        source = r.document_uri or r.document_title or f"{r.source_type}:{r.source_id}"
        context_parts.append(f"[Source {i} - {source}]\n{r.chunk_text}")

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "(No relevant context found.)"

    return f"""{SYSTEM_INSTRUCTION}

## Context

{context_block}

## Question

{question}

## Answer

"""
