"""Content fetchers - stub implementation for MVP."""
from typing import Any, Optional


async def fetch_content(
    source_type: str,
    source_id: str,
    payload: dict[str, Any],
) -> Optional[str]:
    """
    Fetch raw content from source.
    Stub: returns content from payload if present, else placeholder.
    """
    # If payload contains raw text, use it
    if "content" in payload and payload["content"]:
        return str(payload["content"])

    if "body" in payload and payload["body"]:
        return str(payload["body"])

    if "text" in payload and payload["text"]:
        return str(payload["text"])

    # Stub for external fetch (Drive, Jira, etc.) - return placeholder
    return f"Sample content for {source_type}:{source_id}. Replace with real connector."
