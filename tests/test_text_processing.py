"""Tests for text normalization, query building, hashing, and token helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils import text_processing


class TextProcessingTests(unittest.TestCase):
    """Cover the helper functions used across discovery, deduplication, and reporting."""

    def test_canonical_and_normalized_text_helpers(self) -> None:
        self.assertEqual(text_processing.canonical_doi(" https://doi.org/10.1000/ABC "), "10.1000/abc")
        self.assertEqual(text_processing.normalize_text(" A   test\tvalue "), "A test value")
        self.assertEqual(text_processing.normalize_title("A Test: Value!"), "a test value")
        self.assertEqual(text_processing.strip_markup("<p>Hello <b>world</b></p>"), "Hello world")

    def test_reconstruct_inverted_abstract_and_build_query(self) -> None:
        abstract = text_processing.reconstruct_inverted_abstract({"world": [1], "hello": [0]})
        self.assertEqual(abstract, "hello world")
        self.assertEqual(
            text_processing.build_query("topic", ["alpha", "beta"], "AND"),
            "topic AND alpha AND beta",
        )
        self.assertEqual(
            text_processing.build_query("topic", ["alpha"], "custom syntax"),
            "topic custom syntax alpha",
        )
        self.assertEqual(text_processing.build_query("topic", [], None), "topic")

    def test_overlap_and_salient_sentence_helpers(self) -> None:
        score = text_processing.keyword_overlap_score("Large language models help screening", ["language models", "screening"])
        self.assertGreater(score, 0.5)
        self.assertEqual(text_processing.keyword_overlap_score("", ["x"]), 0.0)
        sentence = text_processing.extract_salient_sentence(
            "Background sentence. Large language models help systematic review screening effectively. Tail sentence.",
            ["language models", "screening"],
        )
        self.assertIn("screening", sentence.lower())

    def test_parse_search_terms_supports_multiple_separators_and_sequence_input(self) -> None:
        self.assertEqual(
            text_processing.parse_search_terms("AI governance, generative AI; decision-making\n policy"),
            ["AI governance", "generative AI", "decision-making", "policy"],
        )
        self.assertEqual(
            text_processing.parse_search_terms([" AI governance ", "", "generative AI"]),
            ["AI governance", "generative AI"],
        )
        self.assertEqual(text_processing.parse_search_terms(None), [])

    def test_safe_year_chunking_hashing_slug_and_terms(self) -> None:
        self.assertEqual(text_processing.safe_year("2024"), 2024)
        self.assertIsNone(text_processing.safe_year("1799"))
        self.assertEqual(list(text_processing.chunked(["a", "b", "c"], 2)), [["a", "b"], ["c"]])
        self.assertEqual(
            text_processing.make_query_key("Topic", ["b", "a"], 2020, 2024),
            text_processing.make_query_key("Topic", ["a", "b"], 2020, 2024),
        )
        self.assertEqual(len(text_processing.stable_hash("value", length=12)), 12)
        self.assertEqual(text_processing.slugify_filename(""), "paper")
        self.assertEqual(text_processing.top_terms(["large language models for review", "language models in review"], limit=3)[0], "language")

    def test_ensure_parent_directory_creates_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "nested" / "file.txt"

            text_processing.ensure_parent_directory(target)

            self.assertTrue(target.parent.exists())


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()

