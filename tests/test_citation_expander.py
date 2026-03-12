"""Unit tests for backward and forward citation expansion behavior."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from citation.citation_expander import CitationExpander
from config import ResearchConfig
from models.paper import PaperMetadata


class CitationExpanderTests(unittest.TestCase):
    """Verify citation expansion calls both reference and citation lookups."""

    def _config(self, *, citation_snowballing_enabled: bool = True) -> ResearchConfig:
        return ResearchConfig(
            research_topic="AI-assisted literature reviews",
            search_keywords=["large language models", "screening"],
            max_papers_to_analyze=4,
            citation_snowballing_enabled=citation_snowballing_enabled,
            disable_progress_bars=True,
        ).finalize()

    def test_expand_fetches_backward_and_forward_links_and_updates_database(self) -> None:
        config = self._config()
        database = Mock()
        provider = Mock()
        seed = PaperMetadata(
            database_id=7,
            title="Seed Paper",
            doi="10.1000/seed",
            source="openalex",
            citation_count=15,
            year=2025,
        )
        reference = PaperMetadata(title="Reference Paper", doi="10.1000/reference", source="openalex")
        citation = PaperMetadata(title="Citation Paper", doi="10.1000/citation", source="openalex")
        provider.fetch_references.return_value = [reference]
        provider.fetch_citations.return_value = [citation]

        expanded = CitationExpander(config, database, provider).expand([seed])

        provider.fetch_references.assert_called_once_with(seed, limit=10)
        provider.fetch_citations.assert_called_once_with(seed, limit=10)
        database.update_citations.assert_called_once_with(7, ["10.1000/reference"], ["10.1000/citation"])
        self.assertEqual([paper.title for paper in expanded], ["Reference Paper", "Citation Paper"])
        self.assertTrue(all(paper.query_key == config.query_key for paper in expanded))

    def test_expand_returns_empty_without_calling_provider_when_disabled(self) -> None:
        config = self._config(citation_snowballing_enabled=False)
        database = Mock()
        provider = Mock()
        seed = PaperMetadata(title="Seed Paper", source="openalex")

        expanded = CitationExpander(config, database, provider).expand([seed])

        self.assertEqual(expanded, [])
        provider.fetch_references.assert_not_called()
        provider.fetch_citations.assert_not_called()
        database.update_citations.assert_not_called()


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
