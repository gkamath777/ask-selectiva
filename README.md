# Ask Selectiva — Local AI Knowledge Ingestion & RAG Platform

Fully local AI platform: FastAPI + PostgreSQL/pgvector + Kafka + Ollama + sentence-transformers. No OpenAI or cloud APIs.

---

## 1. Install Ollama

Ollama runs on your **host machine** (not in Docker).

### macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Windows

Download from [ollama.com](https://ollama.com).

### Verify

```bash
ollama serve   # Start server (or it may auto-start)
ollama list    # List installed models
```

---

## 2. Pull Models

```bash
# Default model (8B params)
ollama pull llama3.1:8b

# Optional: larger model for long / “analysis” questions (see OLLAMA_ESCALATION_MODEL)
# ollama pull mixtral
```

---

## 3. Run Docker Compose

```bash
# Start infrastructure + API + consumer
docker compose up -d

# Or build and run
docker compose up -d --build
```

Services:

| Service        | Port | Description                    |
|----------------|------|--------------------------------|
| api            | 8000 | FastAPI application           |
| postgres       | 5432 | PostgreSQL + pgvector         |
| kafka          | 9092 | Kafka broker                   |
| kafka-consumer | -    | Ingestion worker               |

Ollama must be running on the host at `http://localhost:11434`. The API container uses `host.docker.internal` to reach it.

**If `/query` fails with 404 from Ollama:** On the host, run `curl -sS http://127.0.0.1:11434/api/tags` (should list models). The app tries `/api/chat`, then `/api/generate`, then OpenAI-compatible `/v1/chat/completions`. If all return 404, port 11434 is not serving Ollama (another process, or Ollama on a different port — set `OLLAMA_BASE_URL` accordingly). From the API container, open `GET http://localhost:8000/admin/ollama/ping` to see which paths return HTTP status codes vs errors.

---

## 4. Test Webhook

Ingest a document via webhook:

```bash
curl -X POST http://localhost:8000/webhooks/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "source_type": "manual",
    "source_id": "doc-001",
    "title": "Sample Document",
    "uri": "https://example.com/doc-001",
    "content": "This is sample content for RAG. It explains how the system works. The ingestion pipeline fetches, chunks, embeds, and stores documents. The RAG flow embeds the question, searches vectors, and generates answers with Ollama."
  }'
```

Response:

```json
{
  "status": "queued",
  "document_id": "...",
  "message": "Document queued for ingestion"
}
```

Wait a few seconds for the consumer to process, then query.

---

## 5. Query UI & PDF upload

Open http://localhost:8000 in your browser. Use **Upload PDF** to pick a file, then **Ingest PDF** (same **Tenant ID** as for search). Wait a few seconds for the worker to chunk and embed, then ask a question.

**API (multipart):**

```bash
curl -X POST http://localhost:8000/upload/pdf \
  -F "tenant_id=00000000-0000-0000-0000-000000000001" \
  -F "file=@/path/to/your.pdf"
```

Optional form fields: `title`, `source_id` (stable id so re-uploading the same id replaces the document).

PDFs must contain **extractable text**; scanned pages need OCR elsewhere first. Max size 50 MB.

---

## Google Drive (folder watch → ingest PDFs)

Google [Drive push notifications](https://developers.google.com/drive/api/guides/push) call your FastAPI URL when files change under a watched **folder**. The service downloads new or updated **PDFs**, extracts text, and queues them through the same Kafka ingest pipeline as manual uploads.

### One-time setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create or pick a project and **enable the Google Drive API**.
2. Create a **service account**, grant no default org roles needed for Drive; download the JSON key.
3. Open **Google Drive**, create or choose a folder, click **Share**, and add the service account email (looks like `something@PROJECT.iam.gserviceaccount.com`) with **Viewer** access.
4. Copy the folder id from the URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`.
5. Expose your FastAPI app at a **public HTTPS** URL (production domain, reverse proxy, or e.g. [ngrok](https://ngrok.com/) such as `https://abc123.ngrok-free.app`). Google does not deliver webhooks to plain `http://localhost`.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_DRIVE_FOLDER_ID` | Folder id to watch and list PDFs from |
| `GOOGLE_DRIVE_TENANT_ID` | UUID for RAG tenant (same as queries) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Path to the JSON key **or** use `GOOGLE_SERVICE_ACCOUNT_JSON` with the raw JSON |
| `GOOGLE_DRIVE_PUBLIC_BASE_URL` | Public origin only, e.g. `https://your-host.com` (no trailing slash) |
| `GOOGLE_DRIVE_WEBHOOK_TOKEN` | Long random string; must match the `token` query parameter on the webhook URL |

### Register the webhook channel

After the API is up with the env vars set:

```bash
curl -X POST https://YOUR_PUBLIC_HOST/admin/google-drive/watch
```

The app registers `POST /webhooks/google-drive?token=...` with Google. Channels expire (about **7 days**); call `/admin/google-drive/watch` again to renew, or automate it.

Check configuration and channel metadata:

```bash
curl https://YOUR_PUBLIC_HOST/admin/google-drive/status
```

### When you add a PDF to the folder

Google POSTs to `/webhooks/google-drive`. The API verifies `token` and `X-Goog-Channel-ID`, then scans the folder, downloads new or changed PDFs (by `md5Checksum` / `modifiedTime`), and enqueues ingestion.

### Local testing without HTTPS

You cannot register push from localhost. You can still **scan the folder on demand** (credentials + folder + tenant only):

```bash
curl -X POST http://localhost:8000/admin/google-drive/sync-now
```

---

## 6. Test Query (API)

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "question": "How does the ingestion pipeline work?"
  }'
```

Response:

```json
{
  "answer": "...",
  "citations": [
    {"title": "Sample Document", "uri": "https://example.com/doc-001", "source_type": "manual", "source_id": "doc-001"}
  ],
  "model_used": "llama3.1:8b"
}
```

---

## 7. Scale Consumer Workers

Run multiple consumer instances (same consumer group = load balanced):

```bash
# Terminal 1
docker compose run --rm kafka-consumer

# Terminal 2
docker compose run --rm kafka-consumer

# Or scale in compose
docker compose up -d --scale kafka-consumer=3
```

Kafka partitions messages across `ingestion-workers` group members.

---

## Architecture

```
[Webhook] → Kafka (knowledge.ingest.requests) → [Consumer Worker]
                                                      ↓
                                              fetch → chunk → embed → store
                                                      ↓
[Query] → embed question → vector search → Ollama → answer + citations
```

- **Offline ingestion**: Kafka-driven, async, idempotent
- **Online RAG**: Low-latency query path

---

## Model Routing

| Condition                          | Model              |
|------------------------------------|--------------------|
| Question length > 400 chars        | `OLLAMA_ESCALATION_MODEL` (default: same as main) |
| Contains: compare, architecture, design, analysis | `OLLAMA_ESCALATION_MODEL` |
| Default                            | `OLLAMA_MODEL` (e.g. llama3.1:8b) |

---

## Test Scripts

Run the full E2E flow (health → ingest → wait → query):

```bash
# Shell script (default: http://localhost:8000)
./scripts/test.sh

# Or with custom URL
./scripts/test.sh http://localhost:8000

# Python script (no extra deps)
python scripts/test_e2e.py

# Python: ingest only, skip query
python scripts/test_e2e.py --no-query

# Python: custom wait time
python scripts/test_e2e.py --wait 10
```

---

## Health Checks

```bash
curl http://localhost:8000/admin/health
curl http://localhost:8000/admin/health/db
```

---

## Local Development (without Docker)

```bash
# 1. Start Postgres + Kafka only
docker compose up -d postgres kafka zookeeper

# 2. Create venv and install
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# 3. Run Ollama (separate terminal)
ollama serve

# 4. Run API
DATABASE_URL=postgresql+asyncpg://selectiva:selectiva_dev@localhost:5432/ask_selectiva \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
uvicorn app.main:app --reload --port 8000

# 5. Run consumer (separate terminal)
DATABASE_URL=postgresql+asyncpg://selectiva:selectiva_dev@localhost:5432/ask_selectiva \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
python -m app.ingestion.consumer
```

---

## Environment Variables

| Variable              | Default                          | Description                    |
|-----------------------|----------------------------------|--------------------------------|
| DATABASE_URL          | postgresql+asyncpg://...         | PostgreSQL connection string  |
| KAFKA_BOOTSTRAP_SERVERS | localhost:9092                | Kafka brokers                 |
| OLLAMA_BASE_URL       | http://localhost:11434          | Ollama API URL                |
| OLLAMA_MODEL          | llama3.1:8b                       | Default LLM model             |
| OLLAMA_ESCALATION_MODEL | llama3.1:8b                   | Long / trigger questions (pull mixtral and set if you want) |
| OLLAMA_REQUEST_TIMEOUT_SECONDS | 600                   | httpx read timeout waiting on Ollama (raise if ReadTimeout) |
| EMBEDDING_MODEL       | all-MiniLM-L6-v2                | sentence-transformers model   |
| WEBHOOK_SECRET         | (empty)                         | HMAC secret for webhook auth  |
