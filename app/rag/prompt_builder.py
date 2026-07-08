"""RAG prompt construction."""
from app.db.vector_search import SearchResult

SYSTEM_INSTRUCTION = """You are a helpful assistant. Use the provided context as your source of truth.
You may synthesize, summarize, draft, rewrite, structure, or create new deliverables such as proposals when the user asks for them, but factual claims must be grounded in the context.
If required details are missing from the context, include a clearly labeled assumption, placeholder, or open question instead of refusing or inventing facts.
If the context is not relevant to the request, say so clearly.
Cite sources when possible.
Use the conversation history to resolve follow-up references and to answer questions about prior turns.
For factual claims about the knowledge base or outside world, use the retrieved context as the source of truth."""


def build_rag_prompt(
    context_results: list[SearchResult],
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Build prompt with system instruction, context, and question."""
    context_parts = []
    for i, r in enumerate(context_results, 1):
        source = r.document_uri or r.document_title or f"{r.source_type}:{r.source_id}"
        context_parts.append(f"[Source {i} - {source}]\n{r.chunk_text}")

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "(No relevant context found.)"
    history_block = _format_history(history or [])

    return f"""{SYSTEM_INSTRUCTION}

## Conversation History

{history_block}

## Context

{context_block}

## Current Question

Resolve any pronouns, omitted subjects, or phrases like "that", "it", "the previous answer", and "point 2" using the conversation history before answering.

{question}

## Answer

"""


def _format_history(history: list[dict[str, str]]) -> str:
    """Render recent chat turns for follow-up resolution."""
    if not history:
        return "(No prior conversation.)"

    lines = []
    for item in history[-8:]:
        role = item.get("role", "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = item.get("content", "").strip()
        if not content:
            continue
        if len(content) > 1200:
            content = content[:1200].rstrip() + "..."
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")

    return "\n\n".join(lines) if lines else "(No prior conversation.)"
