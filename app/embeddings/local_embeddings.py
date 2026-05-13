"""Local embedding model using sentence-transformers."""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model once and cache."""
    settings = get_settings()
    model = SentenceTransformer(settings.embedding_model)
    logger.info("embedding_model_loaded", model=settings.embedding_model)
    return model


def embed(texts: str | list[str]) -> list[list[float]]:
    """
    Embed text(s) using all-MiniLM-L6-v2.
    Returns normalized vectors (384 dims).
    """
    import numpy as np

    model = _get_model()
    if isinstance(texts, str):
        texts = [texts]
    embeddings = model.encode(texts, normalize_embeddings=True)
    if isinstance(embeddings, np.ndarray):
        if embeddings.ndim == 1:
            return [embeddings.tolist()]
        return [e.tolist() for e in embeddings]
    return list(embeddings)
