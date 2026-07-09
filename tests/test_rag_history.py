"""Tests for RAG conversation history handling."""
import unittest

from app.rag.history import (
    ChatTurn,
    build_retrieval_question,
    decide_history_use,
    format_history,
    normalize_history,
)


class RagHistoryTests(unittest.TestCase):
    def test_normalize_history_keeps_only_valid_turns(self) -> None:
        history = normalize_history(
            [
                {"role": "user", "content": "  Hello  "},
                {"role": "system", "content": "ignore me"},
                {"role": "assistant", "content": ""},
                {"role": "ASSISTANT", "content": "Answer"},
            ]
        )

        self.assertEqual(
            history,
            [
                ChatTurn(role="user", content="Hello"),
                ChatTurn(role="assistant", content="Answer"),
            ],
        )

    def test_decide_history_use_detects_explicit_followup(self) -> None:
        history = [ChatTurn(role="assistant", content="Previous answer")]

        self.assertEqual(decide_history_use("Continue from the previous answer", history), "use")

    def test_decide_history_use_clarifies_ambiguous_reference(self) -> None:
        history = [ChatTurn(role="assistant", content="Previous answer")]

        self.assertEqual(decide_history_use("Can you explain that?", history), "clarify")

    def test_decide_history_use_ignores_standalone_question(self) -> None:
        history = [ChatTurn(role="assistant", content="Previous answer")]

        self.assertEqual(decide_history_use("What is Kafka?", history), "ignore")

    def test_build_retrieval_question_includes_recent_history(self) -> None:
        retrieval_question = build_retrieval_question(
            "What about pricing?",
            [
                ChatTurn(role="user", content="Summarize the proposal"),
                ChatTurn(role="assistant", content="The proposal covers support tiers."),
            ],
        )

        self.assertIn("Current follow-up question:", retrieval_question)
        self.assertIn("What about pricing?", retrieval_question)
        self.assertIn("assistant: The proposal covers support tiers.", retrieval_question)

    def test_format_history_renders_prompt_friendly_turns(self) -> None:
        rendered = format_history(
            [
                ChatTurn(role="user", content="Question"),
                ChatTurn(role="assistant", content="Answer"),
            ]
        )

        self.assertEqual(rendered, "User: Question\n\nAssistant: Answer")


if __name__ == "__main__":
    unittest.main()
