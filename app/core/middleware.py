"""FastAPI middleware for request/response handling."""
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request and response with timing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        path = request.url.path
        method = request.method
        client_host = request.client.host if request.client else None
        quiet_path = path.startswith("/admin/activity/logs")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
        )

        if not quiet_path:
            logger.info(
                "request_started",
                query_string=bool(request.url.query),
                client_host=client_host,
            )
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            if not quiet_path:
                logger.exception(
                    "request_failed",
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id

        if not quiet_path:
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with a Content-Length larger than the configured limit."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        limit = settings.max_webhook_body_bytes if request.url.path.startswith("/webhooks") else settings.max_request_body_bytes
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > limit:
                logger.warning(
                    "request_rejected_too_large",
                    path=request.url.path,
                    content_length=size,
                    limit=limit,
                )
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large; max {limit} bytes"},
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative HTTP security headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response
