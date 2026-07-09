"""Citation compaction helpers."""
from typing import Optional, Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


class CitationSource(Protocol):
    """Minimal result shape needed to build a citation."""

    document_title: str | None
    document_uri: str | None
    source_type: str
    source_id: str


def build_unique_citations(
    results: list[CitationSource],
) -> list[dict[str, Optional[str]]]:
    """Return a compact citation list without repeating the same file/source."""
    citations = []
    seen = set()

    for result in results:
        citation = {
            "title": result.document_title,
            "uri": result.document_uri,
            "source_type": result.source_type,
            "source_id": result.source_id,
        }
        key = citation_key(citation)
        if key in seen:
            continue
        seen.add(key)
        citations.append(citation)

    logger.info(
        "rag_citations_compacted",
        raw_citation_count=len(results),
        citation_count=len(citations),
        omitted_count=max(0, len(results) - len(citations)),
    )
    return citations


def citation_key(citation: dict[str, Optional[str]]) -> str:
    """Group repeated chunks from the same uploaded file or external URI."""
    for value in (citation.get("title"), citation.get("uri"), citation.get("source_id")):
        if value:
            cleaned = value.rstrip("/").split("/")[-1].split("?")[0].strip().lower()
            if cleaned:
                return cleaned
    return f"{citation.get('source_type') or ''}:{citation.get('source_id') or ''}".lower()
