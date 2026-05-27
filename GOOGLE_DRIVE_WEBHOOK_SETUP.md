# Google Drive Webhook Setup

Use this guide to configure a new local machine so Ask Selectiva can ingest PDFs from a Google Drive folder automatically when files are added or changed.

The application supports two Google Drive modes:

- Manual sync: scan the configured folder on demand with `/admin/google-drive/sync-now`.
- Automatic webhook: Google Drive notifies the app when the folder changes, then the app scans and ingests new or changed PDFs.

## What Gets Ingested

Only PDFs are ingested from the configured Google Drive folder.

PDFs must contain extractable text. Scanned image PDFs need OCR before this app can ingest useful text.

## 1. Enable Google Drive API

1. Open Google Cloud Console.
2. Create or select a Google Cloud project.
3. Go to **APIs & Services**.
4. Open **Library**.
5. Search for **Google Drive API**.
6. Click **Enable**.

## 2. Create A Service Account

1. Go to **IAM & Admin**.
2. Open **Service Accounts**.
3. Click **Create service account**.
4. Use a name like `ask-selectiva-drive-reader`.
5. Finish creation.

No broad project role is required if you share the Drive folder directly with the service account.

## 3. Download The Service Account JSON Key

1. Open the service account.
2. Go to **Keys**.
3. Click **Add key**.
4. Choose **Create new key**.
5. Select **JSON**.
6. Download the file.

Place it here on the local machine:

```text
/Users/gauravkamath/Documents/Code/ask-selectiva/secrets/google-service-account.json
```

The `secrets/` folder is ignored by Git and mounted read-only into Docker.

## 4. Share The Google Drive Folder

1. Open the downloaded JSON key.
2. Copy the `client_email` value.
3. Open the Google Drive folder that Ask Selectiva should watch.
4. Click **Share**.
5. Add the service account email.
6. Give it **Viewer** access.

The email looks like:

```text
ask-selectiva-drive-reader@YOUR_PROJECT.iam.gserviceaccount.com
```

## 5. Copy The Google Drive Folder ID

Open the Drive folder in a browser. The URL looks like:

```text
https://drive.google.com/drive/folders/FOLDER_ID_HERE
```

Copy only the folder ID.

## 6. Configure `.env`

From the project root:

```bash
cd /Users/gauravkamath/Documents/Code/ask-selectiva
```

If `.env` does not exist:

```bash
cp .env.example .env
```

Add or update these values:

```env
GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id
GOOGLE_DRIVE_TENANT_ID=00000000-0000-0000-0000-000000000001
GOOGLE_SERVICE_ACCOUNT_FILE=/app/secrets/google-service-account.json
```

These values are enough for manual sync.

## 7. Restart Docker

```bash
docker compose up -d --build
```

Verify the app sees the folder config:

```bash
curl http://localhost:8000/admin/google-drive/status
```

Expected:

```json
{
  "folder_configured": true,
  "tenant_id": "00000000-0000-0000-0000-000000000001"
}
```

Other fields may be `null` or empty before webhook setup.

## 8. Test Manual Sync First

Upload a text-based PDF into the shared Drive folder.

Then run:

```bash
curl -X POST http://localhost:8000/admin/google-drive/sync-now
```

Expected response:

```json
{
  "files_seen": 1,
  "ingested": 1,
  "skipped": 0,
  "failed": 0
}
```

If `skipped` is `1`, the file was already ingested and has not changed.

Watch the ingestion worker:

```bash
docker compose logs -f kafka-consumer
```

## 9. Query The Ingested Document

Use the same tenant ID:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "question": "What is this document about?"
  }'
```

Successful Google Drive citations include:

```json
"source_type": "google_drive"
```

## 10. Configure Automatic Webhook Ingestion

Google Drive cannot call `localhost` directly. For local development, expose the app with ngrok or another public HTTPS tunnel.

Install or configure ngrok, then run:

```bash
ngrok http 8000
```

ngrok will show a forwarding URL:

```text
https://abc123.ngrok-free.app -> http://localhost:8000
```

Use the HTTPS origin in `.env`, without a trailing slash:

```env
GOOGLE_DRIVE_PUBLIC_BASE_URL=https://abc123.ngrok-free.app
```

Generate a webhook token:

```bash
openssl rand -hex 32
```

Add it to `.env`:

```env
GOOGLE_DRIVE_WEBHOOK_TOKEN=your_random_token_here
```

Restart Docker so the containers receive the new values:

```bash
docker compose up -d --build
```

Check status:

```bash
curl http://localhost:8000/admin/google-drive/status
```

Expected:

```json
{
  "folder_configured": true,
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "public_base_url": "https://abc123.ngrok-free.app"
}
```

## 11. Register The Google Drive Watch

Register or renew the Drive webhook channel:

```bash
curl -X POST http://localhost:8000/admin/google-drive/watch
```

Expected response:

```json
{
  "channel_id": "...",
  "resource_id": "...",
  "expiration_ms": 1234567890000,
  "webhook_address_registered": "https://abc123.ngrok-free.app/webhooks/google-drive?token=***"
}
```

Now upload a new text-based PDF to the configured Google Drive folder.

The flow is:

```text
New PDF uploaded to Drive
-> Google calls /webhooks/google-drive
-> Ask Selectiva verifies token and channel
-> app scans the folder
-> new/changed PDFs are downloaded
-> text is extracted
-> Kafka queues ingestion
-> consumer chunks and embeds
-> pgvector stores the chunks
```

## 12. Watch Logs

API logs:

```bash
docker compose logs -f api
```

Consumer logs:

```bash
docker compose logs -f kafka-consumer
```

## 13. Renew The Watch

Google Drive watch channels expire, usually around 7 days.

Renew by calling:

```bash
curl -X POST http://localhost:8000/admin/google-drive/watch
```

You can automate this later with a scheduled job.

## Troubleshooting

### `folder_configured` is false

The app does not see `GOOGLE_DRIVE_FOLDER_ID`.

Check `.env`, then restart Docker:

```bash
docker compose up -d --build
```

### `tenant_id` is null

The app does not see `GOOGLE_DRIVE_TENANT_ID`.

Use:

```env
GOOGLE_DRIVE_TENANT_ID=00000000-0000-0000-0000-000000000001
```

### `sync-now` says credentials are missing

Confirm:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=/app/secrets/google-service-account.json
```

Also confirm the file exists locally:

```text
/Users/gauravkamath/Documents/Code/ask-selectiva/secrets/google-service-account.json
```

### Google Drive cannot access the webhook

Make sure:

- ngrok is running.
- `GOOGLE_DRIVE_PUBLIC_BASE_URL` uses `https://`.
- There is no trailing slash.
- Docker was restarted after editing `.env`.
- `/admin/google-drive/watch` was called after setting the public URL.

### Uploaded PDFs are not searchable

Check:

- The PDF contains extractable text.
- `docker compose logs -f kafka-consumer` shows successful processing.
- You query using the same `GOOGLE_DRIVE_TENANT_ID`.

