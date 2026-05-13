"""RAG prompt construction."""
from app.db.vector_search import SearchResult

SYSTEM_INSTRUCTION = """You are a helpful assistant. Answer the question based ONLY on the provided context.
If the context does not contain relevant information, say so clearly.
Do not make up information. Cite sources when possible."""


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
