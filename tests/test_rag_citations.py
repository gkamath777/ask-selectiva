"""Tests for RAG citation compaction."""
import sys
import types
import unittest
from types import SimpleNamespace

structlog_stub = types.SimpleNamespace(
    get_logger=lambda _name: types.SimpleNamespace(info=lambda *_args, **_kwargs: None),
    stdlib=types.SimpleNamespace(BoundLogger=object),
)
sys.modules.setdefault("structlog", structlog_stub)

from app.rag.citations import build_unique_citations, citation_key


class RagCitationTests(unittest.TestCase):
    def test_citation_key_prefers_file_name(self) -> None:
        self.assertEqual(
            citation_key(
                {
                    "title": "Benefits.pdf",
                    "uri": "https://example.com/other.pdf",
                    "source_type": "manual",
                    "source_id": "doc-1",
                }
            ),
            "benefits.pdf",
        )

    def test_build_unique_citations_dedupes_without_capping(self) -> None:
        results = [
            _citation_source("Benefits.pdf", None, "manual", "doc-1"),
            _citation_source("Benefits.pdf", None, "manual", "doc-1"),
            _citation_source("Plan.pdf", None, "manual", "doc-2"),
            _citation_source("Extra.pdf", None, "manual", "doc-3"),
        ]

        citations = build_unique_citations(results)

        self.assertEqual(
            citations,
            [
                {
                    "title": "Benefits.pdf",
                    "uri": None,
                    "source_type": "manual",
                    "source_id": "doc-1",
                },
                {
                    "title": "Plan.pdf",
                    "uri": None,
                    "source_type": "manual",
                    "source_id": "doc-2",
                },
                {
                    "title": "Extra.pdf",
                    "uri": None,
                    "source_type": "manual",
                    "source_id": "doc-3",
                },
            ],
        )


def _citation_source(
    document_title: str | None,
    document_uri: str | None,
    source_type: str,
    source_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        document_title=document_title,
        document_uri=document_uri,
        source_type=source_type,
        source_id=source_id,
    )


if __name__ == "__main__":
    unittest.main()
