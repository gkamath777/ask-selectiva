"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.api.routes_admin import router as admin_router
from app.api.routes_google_drive import admin_router as google_drive_admin_router
from app.api.routes_google_drive import webhook_router as google_drive_webhook_router
from app.api.routes_query import router as query_router
from app.api.routes_upload import router as upload_router
from app.api.routes_webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestLoggingMiddleware, RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.db.session import init_db
from app.kafka.producer import shutdown_producer

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # Startup
    logger.info("application_starting", log_level=settings.log_level)
    await init_db()
    logger.info("application_started")

    yield

    # Shutdown
    logger.info("application_stopping")
    await shutdown_producer()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Create FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Ask Selectiva",
        description="Local AI Knowledge Ingestion & RAG Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials="*" not in settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhooks_router)
    app.include_router(google_drive_webhook_router)
    app.include_router(upload_router)
    app.include_router(query_router)
    app.include_router(admin_router)
    app.include_router(google_drive_admin_router)
    logger.info("application_routes_registered")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(request: Request, exc: StarletteHTTPException):
        """Log expected HTTP errors with request context before default handling."""
        logger.warning(
            "http_exception",
            path=str(request.url.path),
            status_code=exc.status_code,
            detail=str(exc.detail),
        )
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_exception(request: Request, exc: RequestValidationError):
        """Log validation errors without dumping request bodies."""
        logger.warning(
            "request_validation_failed",
            path=str(request.url.path),
            error_count=len(exc.errors()),
        )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return JSON on unexpected errors so the web UI can parse responses."""
        logger.exception("unhandled_exception", path=str(request.url.path), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc) or "Internal server error"},
        )

    static_dir = Path(__file__).resolve().parent / "static"
    index_path = static_dir / "index.html"
    index_html = (
        index_path.read_text(encoding="utf-8")
        if index_path.is_file()
        else "<p>Static UI missing: app/static/index.html</p>"
    )

    # Register / before any mounts — Starlette matches mount routes in order.
    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        return HTMLResponse(index_html)

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info("static_assets_mounted", static_dir=str(static_dir))
    else:
        logger.warning("static_assets_missing", static_dir=str(static_dir))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
