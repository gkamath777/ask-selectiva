#!/usr/bin/env bash
# Ask Selectiva - E2E test script
# Usage: ./scripts/test.sh [BASE_URL]
# Default: BASE_URL=http://localhost:8000

set -e

BASE_URL="${1:-http://localhost:8000}"
TENANT_ID="00000000-0000-0000-0000-000000000001"

echo "=== Ask Selectiva E2E Test ==="
echo "Base URL: $BASE_URL"
echo ""

# 1. Health check
echo "1. Health check..."
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/admin/health")
if [ "$HEALTH" != "200" ]; then
  echo "   FAIL: Health check returned $HEALTH (expected 200)"
  exit 1
fi
echo "   OK"

# 2. DB health
echo "2. DB health..."
DB_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/admin/health/db")
if [ "$DB_HEALTH" != "200" ]; then
  echo "   FAIL: DB health returned $DB_HEALTH (expected 200)"
  exit 1
fi
echo "   OK"

# 3. Ingest document
echo "3. Ingest document..."
INGEST_RESP=$(curl -s -X POST "$BASE_URL/webhooks/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"source_type\": \"manual\",
    \"source_id\": \"doc-test-$(date +%s)\",
    \"title\": \"Test Document\",
    \"uri\": \"https://example.com/test-doc\",
    \"content\": \"This is test content for RAG. The ingestion pipeline fetches, chunks, embeds, and stores documents. The RAG flow embeds the question, searches vectors, and generates answers with Ollama.\"
  }")

if echo "$INGEST_RESP" | grep -q '"status":"queued"'; then
  echo "   OK"
  echo "   Response: $INGEST_RESP"
else
  echo "   FAIL: $INGEST_RESP"
  exit 1
fi

# 4. Wait for consumer to process
echo "4. Waiting 8s for consumer..."
sleep 8

# 5. Query
echo "5. Query..."
QUERY_RESP=$(curl -s -X POST "$BASE_URL/query" \
  -H "Content-Type: application/json" \
  -d "{
    \"tenant_id\": \"$TENANT_ID\",
    \"question\": \"How does the ingestion pipeline work?\"
  }")

if echo "$QUERY_RESP" | grep -q '"answer"'; then
  echo "   OK"
  echo ""
  echo "Response:"
  echo "$QUERY_RESP" | python3 -m json.tool 2>/dev/null || echo "$QUERY_RESP"
else
  echo "   FAIL: $QUERY_RESP"
  exit 1
fi

echo ""
echo "=== All tests passed ==="
