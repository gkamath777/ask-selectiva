"""Text chunking with overlap."""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Split text into chunks with overlap.
    chunk_size: target characters per chunk
    overlap: overlapping characters between chunks
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence or word boundary
        if end < len(text):
            last_period = chunk.rfind(". ")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > chunk_size // 2:
                chunk = chunk[: break_point + 1]
                end = start + break_point + 1

        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start >= len(text):
            break

    return chunks
