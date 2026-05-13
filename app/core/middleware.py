"""FastAPI middleware for request/response handling."""
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request and response with timing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", "")
        path = request.url.path
        method = request.method

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "request_completed",
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
        )
        return response
