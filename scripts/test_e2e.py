#!/usr/bin/env python3
"""
Ask Selectiva - E2E test script.
Usage: python scripts/test_e2e.py [--base-url URL] [--no-query]
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

DEFAULT_BASE_URL = "http://localhost:8000"
TENANT_ID = "00000000-0000-0000-0000-000000000001"


def request(
    method: str,
    url: str,
    data: dict | None = None,
    *,
    timeout_sec: float = 30,
) -> tuple[int, dict | str]:
    """Make HTTP request, return (status_code, body)."""
    req_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=req_data,
        method=method,
        headers={"Content-Type": "application/json"} if req_data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask Selectiva E2E tests")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--no-query",
        action="store_true",
        help="Skip query step (ingest only)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=8,
        help="Seconds to wait for consumer after ingest (default: 8)",
    )
    parser.add_argument(
        "--query-timeout",
        type=int,
        default=600,
        help="Seconds to wait for /query (LLM generation; default: 600)",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    errors = []

    # 1. Health
    print("1. Health check...", end=" ")
    status, _ = request("GET", f"{base}/admin/health")
    if status != 200:
        errors.append(f"Health check: {status}")
        print("FAIL")
    else:
        print("OK")

    # 2. DB health
    print("2. DB health...", end=" ")
    status, _ = request("GET", f"{base}/admin/health/db")
    if status != 200:
        errors.append(f"DB health: {status}")
        print("FAIL")
    else:
        print("OK")

    # 3. Ingest
    print("3. Ingest document...", end=" ")
    doc_id = f"doc-test-{int(time.time())}"
    status, body = request(
        "POST",
        f"{base}/webhooks/ingest",
        {
            "tenant_id": TENANT_ID,
            "source_type": "manual",
            "source_id": doc_id,
            "title": "Test Document",
            "uri": "https://example.com/test-doc",
            "content": "This is test content for RAG. The ingestion pipeline fetches, chunks, embeds, and stores documents. The RAG flow embeds the question, searches vectors, and generates answers with Ollama.",
        },
    )
    if status != 200 or (isinstance(body, dict) and body.get("status") != "queued"):
        errors.append(f"Ingest: {status} {body}")
        print("FAIL")
    else:
        print("OK")
        if isinstance(body, dict):
            print(f"   Document ID: {body.get('document_id', '?')}")

    if args.no_query:
        return 0 if not errors else 1

    # 4. Wait
    print(f"4. Waiting {args.wait}s for consumer...")
    time.sleep(args.wait)

    # 5. Query
    print("5. Query...", end=" ")
    try:
        status, body = request(
            "POST",
            f"{base}/query",
            {"tenant_id": TENANT_ID, "question": "How does the ingestion pipeline work?"},
            timeout_sec=args.query_timeout,
        )
    except TimeoutError:
        errors.append(f"Query: timed out after {args.query_timeout}s (try --query-timeout)")
        print("FAIL")
        status = 0  # sentinel for below
        body = None
    else:
        if status != 200:
            errors.append(f"Query: {status} {body}")
            print("FAIL")
        else:
            print("OK")
            if isinstance(body, dict):
                print("\nResponse:")
                print(json.dumps(body, indent=2))

    if errors:
        print("\nErrors:", errors)
        return 1
    print("\n=== All tests passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
