"""Google Drive push notifications and admin watch/sync."""
import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import crud
from app.db.session import DbSession, async_session_factory
from app.integrations.google_drive import (
    assert_drive_ingest_config,
    assert_drive_minimal,
    build_drive_service,
    drive_push_webhook_address,
    stop_channel_sync,
    sync_folder_pdfs_to_pipeline,
    watch_folder_sync,
)

logger = get_logger(__name__)

webhook_router = APIRouter(prefix="/webhooks", tags=["google-drive"])
admin_router = APIRouter(prefix="/admin/google-drive", tags=["google-drive"])


async def _run_drive_sync_safe() -> None:
    async with async_session_factory() as session:
        try:
            summary = await sync_folder_pdfs_to_pipeline(session)
            logger.info("google_drive_sync_finished", **summary)
        except Exception:
            await session.rollback()
            logger.exception("google_drive_sync_failed")


@webhook_router.post("/google-drive")
async def google_drive_push(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str | None = Query(None),
) -> Response:
    """
    Google calls this URL when the watched Drive folder changes (push notification).
    Requires HTTPS and a public hostname. Register the channel with POST /admin/google-drive/watch.
    """
    settings = get_settings()
    if not settings.google_drive_folder_id:
        raise HTTPException(status_code=404, detail="Google Drive ingestion is not configured")

    try:
        assert_drive_ingest_config(settings)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if not settings.google_drive_webhook_token or token != settings.google_drive_webhook_token:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    channel_header = request.headers.get("X-Goog-Channel-ID")
    if not channel_header:
        raise HTTPException(status_code=400, detail="Missing X-Goog-Channel-ID")

    async with async_session_factory() as session:
        state = await crud.get_drive_channel_state(session)
        if not state or state.channel_id != channel_header:
            raise HTTPException(status_code=401, detail="Unknown notification channel")

    # Respond quickly; sync runs in background
    background_tasks.add_task(_run_drive_sync_safe)
    return Response(status_code=200)


@admin_router.post("/watch")
async def register_drive_watch(session: DbSession) -> dict:
    """
    Create or renew a Drive push channel for GOOGLE_DRIVE_FOLDER_ID.
    Google expires channels (~7 days); call this again before expiry or on deploy.
    """
    settings = get_settings()
    try:
        assert_drive_ingest_config(settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not settings.google_drive_public_base_url.lower().startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_DRIVE_PUBLIC_BASE_URL must be https:// (Google requires HTTPS for web_hook)",
        )

    address = drive_push_webhook_address(settings)
    channel_uuid = str(uuid.uuid4())

    svc = await asyncio.to_thread(build_drive_service, settings)

    prev = await crud.get_drive_channel_state(session)
    if prev and prev.resource_id and prev.channel_id:
        try:
            await asyncio.to_thread(stop_channel_sync, svc, prev.channel_id, prev.resource_id)
        except Exception as e:
            logger.warning("drive_stop_previous_channel_failed", error=str(e))

    try:
        watch_resp = await asyncio.to_thread(
            watch_folder_sync, svc, settings.google_drive_folder_id or "", address, channel_uuid
        )
    except Exception as e:
        logger.exception("drive_watch_failed", error=str(e))
        raise HTTPException(status_code=502, detail=f"Drive watch failed: {e!s}") from e

    exp = watch_resp.get("expiration")
    exp_int = int(exp) if exp is not None else None

    await crud.upsert_drive_channel_state(
        session,
        channel_id=channel_uuid,
        resource_id=watch_resp.get("resourceId"),
        expiration_ms=exp_int,
    )

    return {
        "channel_id": channel_uuid,
        "resource_id": watch_resp.get("resourceId"),
        "expiration_ms": exp_int,
        "webhook_address_registered": address.split("?")[0] + "?token=***",
    }


@admin_router.get("/status")
async def drive_status(session: DbSession) -> dict:
    settings = get_settings()
    state = await crud.get_drive_channel_state(session)
    return {
        "folder_configured": bool(settings.google_drive_folder_id),
        "tenant_id": settings.google_drive_tenant_id,
        "public_base_url": settings.google_drive_public_base_url,
        "channel_id": state.channel_id if state else None,
        "expiration_ms": state.expiration_ms if state else None,
    }


@admin_router.post("/sync-now")
async def drive_sync_now(session: DbSession) -> dict:
    """Manually scan the folder and queue new/changed PDFs (same as push handler)."""
    settings = get_settings()
    try:
        assert_drive_minimal(settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    summary = await sync_folder_pdfs_to_pipeline(session)
    return summary
