"""Google Drive API: list PDFs, download, watch folder for push notifications."""
from __future__ import annotations

import asyncio
import json
import uuid
from io import BytesIO
from typing import Any, Optional
from urllib.parse import quote

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db import crud
from app.ingestion.pdf_extract import extract_text_from_pdf
from app.kafka.ingest_publish import publish_ingest_for_document

logger = get_logger(__name__)

DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)


def drive_credentials(settings: Settings):
    """Build service account credentials for Drive readonly."""
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        return service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
    if settings.google_service_account_file:
        return service_account.Credentials.from_service_account_file(
            settings.google_service_account_file,
            scopes=DRIVE_SCOPES,
        )
    raise ValueError("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE")


def build_drive_service(settings: Settings):
    creds = drive_credentials(settings)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_pdf_files_in_folder_sync(service, folder_id: str) -> list[dict[str, Any]]:
    """List PDF files directly under folder_id."""
    q = (
        f"'{folder_id}' in parents and "
        "mimeType = 'application/pdf' and "
        "trashed = false"
    )
    out: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, md5Checksum, modifiedTime, webViewLink)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        out.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def download_file_bytes_sync(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def watch_folder_sync(service, folder_id: str, webhook_address: str, channel_uuid: str) -> dict[str, Any]:
    """Register push notifications for a folder (Drive treats folders as files)."""
    body = {"id": channel_uuid, "type": "web_hook", "address": webhook_address}
    return (
        service.files()
        .watch(fileId=folder_id, body=body, supportsAllDrives=True)
        .execute()
    )


def stop_channel_sync(service, channel_id: str, resource_id: str) -> None:
    try:
        service.channels().stop(body={"id": channel_id, "resourceId": resource_id}).execute()
    except HttpError as e:
        if e.resp.status in (404, 410):
            logger.info("drive_channel_already_stopped", status=e.resp.status)
            return
        raise


def drive_push_webhook_address(settings: Settings) -> str:
    base = (settings.google_drive_public_base_url or "").rstrip("/")
    path = "/webhooks/google-drive"
    token = settings.google_drive_webhook_token
    if token:
        return f"{base}{path}?token={quote(token, safe='')}"
    return f"{base}{path}"


def assert_drive_minimal(settings: Settings) -> None:
    """Folder, tenant, and credentials — enough to call Drive API or /sync-now."""
    if not settings.google_drive_folder_id:
        raise ValueError("GOOGLE_DRIVE_FOLDER_ID is required")
    if not settings.google_drive_tenant_id:
        raise ValueError("GOOGLE_DRIVE_TENANT_ID is required")
    if not settings.google_service_account_json and not settings.google_service_account_file:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE is required")


def assert_drive_ingest_config(settings: Settings) -> None:
    """Full config for push notifications (HTTPS webhook + token)."""
    assert_drive_minimal(settings)
    if not settings.google_drive_public_base_url:
        raise ValueError("GOOGLE_DRIVE_PUBLIC_BASE_URL is required (https://...)")
    if not settings.google_drive_webhook_token:
        raise ValueError("GOOGLE_DRIVE_WEBHOOK_TOKEN is required for verified push notifications")


async def sync_folder_pdfs_to_pipeline(session: AsyncSession) -> dict[str, Any]:
    """
    List PDFs in configured folder; enqueue any new or changed files for ingestion.
    Call after a Drive push notification or manually from admin.
    """
    settings = get_settings()
    assert_drive_minimal(settings)
    tenant_id = uuid.UUID(settings.google_drive_tenant_id or "")
    folder_id = settings.google_drive_folder_id or ""

    service = await asyncio.to_thread(build_drive_service, settings)
    files = await asyncio.to_thread(list_pdf_files_in_folder_sync, service, folder_id)

    ingested = 0
    skipped = 0
    failed = 0

    for fmeta in files:
        file_id = fmeta["id"]
        name = fmeta.get("name") or file_id
        md5 = fmeta.get("md5Checksum") or ""
        modified = fmeta.get("modifiedTime") or ""
        link = fmeta.get("webViewLink")
        fingerprint = md5 or modified
        if not fingerprint:
            fingerprint = file_id

        existing = await crud.get_document_by_tenant_source(session, tenant_id, "google_drive", file_id)
        if existing and existing.content_hash == fingerprint:
            skipped += 1
            continue

        try:
            raw = await asyncio.to_thread(download_file_bytes_sync, service, file_id)
            text = extract_text_from_pdf(raw)
        except Exception as e:
            failed += 1
            logger.warning("drive_pdf_fetch_or_parse_failed", file_id=file_id, error=str(e))
            continue

        if not text:
            failed += 1
            logger.warning("drive_pdf_no_extractable_text", file_id=file_id, name=name)
            continue

        payload = {
            "tenant_id": str(tenant_id),
            "source_type": "google_drive",
            "source_id": file_id,
            "title": name,
            "uri": link,
            "content": text,
        }

        doc = await crud.upsert_document(
            session,
            tenant_id=tenant_id,
            source_type="google_drive",
            source_id=file_id,
            title=name,
            uri=link,
            content_hash=fingerprint,
            status="queued",
        )
        await session.commit()

        ok = await publish_ingest_for_document(
            session,
            document_id=doc.id,
            tenant_id=tenant_id,
            source_type="google_drive",
            source_id=file_id,
            payload=payload,
            translate_to_http=False,
        )
        if ok:
            ingested += 1
        else:
            failed += 1
        logger.info("drive_pdf_queued", document_id=str(doc.id), file_id=file_id, name=name)

    return {"files_seen": len(files), "ingested": ingested, "skipped": skipped, "failed": failed}
