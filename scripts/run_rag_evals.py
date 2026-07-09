#!/usr/bin/env python3
"""Run lightweight API-level RAG evals against a live Ask Selectiva instance."""
import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_EVAL_FILE = Path("evals/rag_smoke.jsonl")


def request(
    method: str,
    url: str,
    data: dict[str, Any] | None = None,
    *,
    timeout_sec: float = 30,
) -> tuple[int, dict[str, Any] | str]:
    """Make an HTTP request and decode JSON when possible."""
    req_data = json.dumps(data).encode() if data is not None else None
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


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load JSONL eval cases."""
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
    return cases


def score_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Score citation source hits and answer term checks."""
    citations = response.get("citations") or []
    answer = str(response.get("answer") or "")
    answer_lower = answer.lower()
    cited_source_ids = {
        str(c.get("source_id"))
        for c in citations
        if isinstance(c, dict) and c.get("source_id") is not None
    }

    expected_source_ids = {str(s) for s in case.get("expected_source_ids", [])}
    allowed_source_ids = {str(s) for s in case.get("allowed_source_ids", expected_source_ids)}
    required_terms = [str(t) for t in case.get("required_answer_terms", [])]
    forbidden_terms = [str(t) for t in case.get("forbidden_answer_terms", [])]

    missing_sources = sorted(expected_source_ids - cited_source_ids)
    unexpected_sources = sorted(cited_source_ids - allowed_source_ids) if allowed_source_ids else []
    missing_terms = [term for term in required_terms if term.lower() not in answer_lower]
    forbidden_hits = [term for term in forbidden_terms if term.lower() in answer_lower]

    passed = not missing_sources and not unexpected_sources and not missing_terms and not forbidden_hits
    return {
        "passed": passed,
        "missing_sources": missing_sources,
        "unexpected_sources": unexpected_sources,
        "missing_terms": missing_terms,
        "forbidden_hits": forbidden_hits,
        "cited_source_ids": sorted(cited_source_ids),
        "answer_chars": len(answer),
        "answer_excerpt": answer[:500],
        "model_used": response.get("model_used"),
    }


def ingest_documents(base_url: str, case: dict[str, Any]) -> list[str]:
    """Queue all documents for an eval case and return document ids."""
    document_ids = []
    for doc in case.get("documents", []):
        payload = {
            "tenant_id": case["tenant_id"],
            "source_type": doc.get("source_type", "eval"),
            "source_id": doc["source_id"],
            "title": doc.get("title"),
            "uri": doc.get("uri"),
            "content": doc["content"],
            "metadata": {"eval_case": case["name"]},
        }
        status, body = request("POST", f"{base_url}/webhooks/ingest", payload)
        if status != 200 or not isinstance(body, dict) or body.get("status") != "queued":
            raise RuntimeError(f"ingest failed for {doc['source_id']}: {status} {body}")
        document_ids.append(str(body.get("document_id")))
    return document_ids


def wait_for_documents(base_url: str, document_ids: list[str], timeout_sec: int) -> None:
    """Wait until all queued eval documents are ready."""
    deadline = time.time() + timeout_sec
    pending = set(document_ids)
    while pending and time.time() < deadline:
        for document_id in list(pending):
            status, body = request("GET", f"{base_url}/admin/documents/{document_id}/status")
            if status == 200 and isinstance(body, dict) and body.get("status") == "ready":
                pending.remove(document_id)
        if pending:
            time.sleep(1)
    if pending:
        raise TimeoutError(f"documents not ready after {timeout_sec}s: {sorted(pending)}")


def run_case(
    base_url: str,
    case: dict[str, Any],
    *,
    ingest_timeout: int,
    query_timeout: int,
) -> dict[str, Any]:
    """Run one eval case end to end."""
    start = time.perf_counter()
    document_ids = ingest_documents(base_url, case)
    wait_for_documents(base_url, document_ids, ingest_timeout)

    status, body = request(
        "POST",
        f"{base_url}/query",
        {"tenant_id": case["tenant_id"], "question": case["question"]},
        timeout_sec=query_timeout,
    )
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"query failed: {status} {body}")

    score = score_case(case, body)
    score["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
    score["name"] = case["name"]
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Ask Selectiva RAG evals")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--ingest-timeout", type=int, default=60)
    parser.add_argument("--query-timeout", type=int, default=600)
    parser.add_argument(
        "--reuse-tenants",
        action="store_true",
        help="Use tenant_id values from the eval file instead of generating isolated per-run tenants",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    cases = load_cases(args.eval_file)
    if not args.reuse_tenants:
        run_id = uuid.uuid4()
        for index, case in enumerate(cases):
            case["tenant_id"] = str(uuid.uuid5(run_id, f"{index}:{case['name']}"))
    results = []

    for case in cases:
        try:
            result = run_case(
                base_url,
                case,
                ingest_timeout=args.ingest_timeout,
                query_timeout=args.query_timeout,
            )
        except Exception as e:
            result = {"name": case.get("name", "<unnamed>"), "passed": False, "error": str(e)}
        results.append(result)

    passed_count = sum(1 for r in results if r["passed"])
    summary = {"passed": passed_count, "total": len(results), "results": results}

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"RAG evals: {passed_count}/{len(results)} passed")
        for result in results:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"- {status} {result['name']}")
            for key in ("error", "missing_sources", "unexpected_sources", "missing_terms", "forbidden_hits"):
                if result.get(key):
                    print(f"  {key}: {result[key]}")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
