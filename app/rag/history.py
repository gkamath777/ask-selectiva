"""Conversation history helpers for RAG follow-up handling."""
from dataclasses import dataclass
from typing import Literal

HistoryDecision = Literal["use", "ignore", "clarify"]

VALID_ROLES = {"user", "assistant"}


@dataclass(frozen=True)
class ChatTurn:
    """A sanitized chat turn that can be safely used in prompts and retrieval."""

    role: str
    content: str


def normalize_history(history: list[dict[str, str]] | None) -> list[ChatTurn]:
    """Convert request history dictionaries into valid, trimmed chat turns."""
    turns = []
    for item in history or []:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in VALID_ROLES and content:
            turns.append(ChatTurn(role=role, content=content))
    return turns


def decide_history_use(question: str, history: list[ChatTurn]) -> HistoryDecision:
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


def build_retrieval_question(question: str, history: list[ChatTurn]) -> str:
    """Add recent turns to retrieval text so short follow-ups search the right concepts."""
    recent_lines = []
    for turn in history[-6:]:
        content = turn.content
        if len(content) > 700:
            content = content[:700].rstrip() + "..."
        recent_lines.append(f"{turn.role}: {content}")

    if not recent_lines:
        return question

    return (
        f"Current follow-up question:\n{question}\n\n"
        "Relevant recent conversation for resolving the follow-up:\n"
        + "\n".join(recent_lines)
    )


def format_history(history: list[ChatTurn]) -> str:
    """Render recent chat turns for follow-up resolution."""
    if not history:
        return "(No prior conversation.)"

    lines = []
    for turn in history[-8:]:
        content = turn.content
        if len(content) > 1200:
            content = content[:1200].rstrip() + "..."
        label = "User" if turn.role == "user" else "Assistant"
        lines.append(f"{label}: {content}")

    return "\n\n".join(lines) if lines else "(No prior conversation.)"
