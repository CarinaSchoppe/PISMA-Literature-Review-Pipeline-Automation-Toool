"""Tests for record deduplication across overlapping discovery sources."""

from __future__ import annotations

import unittest

from models.paper import PaperMetadata

from utils.deduplication import deduplicate_papers


class DeduplicationTests(unittest.TestCase):
    """Verify DOI-based and title-based merge behavior."""

    def test_merges_same_doi_records(self) -> None:
        papers = [
            PaperMetadata(
                title="Large language models for screening",
                authors=["Alice"],
                abstract="short",
                year=2024,
                doi="10.1000/test",
                source="openalex",
                citation_count=10,
            ),
            PaperMetadata(
                title="Large language models for screening",
                authors=["Bob"],
                abstract="a much longer abstract for the same paper",
                year=2024,
                doi="https://doi.org/10.1000/test",
                source="crossref",
                citation_count=15,
            ),
        ]

        deduplicated = deduplicate_papers(papers)

        self.assertEqual(len(deduplicated), 1)
        self.assertIn("Alice", deduplicated[0].authors)
        self.assertIn("Bob", deduplicated[0].authors)
        self.assertEqual(deduplicated[0].citation_count, 15)
        self.assertEqual(deduplicated[0].abstract, "a much longer abstract for the same paper")

    def test_merges_highly_similar_titles_without_dois(self) -> None:
        papers = [
            PaperMetadata(
                title="Large language models for review screening",
                authors=["Alice"],
                abstract="short",
                year=2024,
                source="openalex",
            ),
            PaperMetadata(
                title="Large language models for systematic review screening",
                authors=["Bob"],
                abstract="longer abstract",
                year=2024,
                source="crossref",
            ),
        ]

        deduplicated = deduplicate_papers(papers, title_similarity_threshold=0.6)

        self.assertEqual(len(deduplicated), 1)
        self.assertIn("Alice", deduplicated[0].authors)
        self.assertIn("Bob", deduplicated[0].authors)
        self.assertEqual(deduplicated[0].abstract, "longer abstract")

    def test_keeps_distinct_title_only_records_when_similarity_is_low(self) -> None:
        papers = [
            PaperMetadata(title="Clinical benchmark for triage", source="openalex"),
            PaperMetadata(title="Autonomous agents for software repair", source="crossref"),
        ]

        deduplicated = deduplicate_papers(papers, title_similarity_threshold=0.95)

        self.assertEqual(len(deduplicated), 2)

    def test_returns_identity_records_directly_when_all_have_dois(self) -> None:
        papers = [
            PaperMetadata(title="Paper One", doi="10.1000/one", source="openalex"),
            PaperMetadata(title="Paper Two", doi="10.1000/two", source="crossref"),
        ]

        deduplicated = deduplicate_papers(papers)

        self.assertEqual(len(deduplicated), 2)
