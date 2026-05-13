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
from app.core.middleware import RequestLoggingMiddleware
from app.db.session import init_db
from app.kafka.producer import shutdown_producer

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # Startup
    await init_db()
    logger.info("application_started")

    yield

    # Shutdown
    await shutdown_producer()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Ask Selectiva",
        description="Local AI Knowledge Ingestion & RAG Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhooks_router)
    app.include_router(google_drive_webhook_router)
    app.include_router(upload_router)
    app.include_router(query_router)
    app.include_router(admin_router)
    app.include_router(google_drive_admin_router)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return JSON on unexpected errors so the web UI can parse responses."""
        if isinstance(exc, StarletteHTTPException):
            return await http_exception_handler(request, exc)
        if isinstance(exc, RequestValidationError):
            return await request_validation_exception_handler(request, exc)
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
