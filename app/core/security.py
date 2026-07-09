"""Lightweight API-key protection for non-webhook endpoints."""
from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    """Require X-API-Key when API_KEY is configured."""
    settings = get_settings()
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        logger.warning("api_key_auth_failed", has_api_key=bool(x_api_key))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
