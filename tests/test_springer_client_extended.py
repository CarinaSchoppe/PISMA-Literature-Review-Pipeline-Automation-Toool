"""Additional tests for Springer discovery behavior and record normalization."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from config import ResearchConfig
from discovery.springer_client import SpringerClient


class SpringerClientExtendedTests(unittest.TestCase):
    """Exercise Springer's API-key guardrails, pagination, and parsing branches."""

    def _config(self, **overrides) -> ResearchConfig:
        payload = {
            "research_topic": "Large language models",
            "search_keywords": ["survey", "benchmark"],
            "pages_to_retrieve": 2,
            "results_per_page": 2,
            "springer_enabled": True,
            "include_pubmed": False,
            "api_settings": {"springer_api_key": "springer-key"},
        }
        payload.update(overrides)
        return ResearchConfig(
            **payload,
        ).finalize()

    def test_search_returns_empty_without_api_key(self) -> None:
        config = self._config(api_settings={"springer_api_key": None})

        results = SpringerClient(config).search()

        self.assertEqual(results, [])

    def test_search_filters_years_and_stops_when_page_is_short(self) -> None:
        config = self._config(year_range_start=2023, year_range_end=2026, discovery_strategy="precise", pages_to_retrieve=1)
        payload = {
            "records": [
                {
                    "title": "Springer Survey",
                    "creators": [{"creator": "Ada Lovelace"}],
                    "abstract": "<p>Abstract</p>",
                    "publicationDate": "2024-01-01",
                    "publicationName": "AI Journal",
                    "doi": "10.1000/springer",
                    "openaccess": "true",
                    "url": [{"format": "pdf", "value": "https://example.org/springer.pdf"}],
                },
                {
                    "title": "Old Paper",
                    "creators": ["Grace Hopper"],
                    "abstract": "",
                    "publicationDate": "2019-01-01",
                    "publicationName": "Old Journal",
                    "identifier": "old-id",
                    "openaccess": "false",
                    "url": [],
                },
            ]
        }

        with patch("discovery.springer_client.request_json", return_value=payload) as request_json_mock:
            results = SpringerClient(config).search()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Springer Survey")
        self.assertEqual(results[0].authors, ["Ada Lovelace"])
        self.assertEqual(results[0].pdf_link, "https://example.org/springer.pdf")
        self.assertTrue(results[0].open_access)
        request_json_mock.assert_called_once()

    def test_search_breaks_on_empty_pages_and_per_source_limit(self) -> None:
        empty_config = self._config(discovery_strategy="precise", pages_to_retrieve=2, results_per_page=1)
        with patch("discovery.springer_client.request_json", return_value=None):
            self.assertEqual(SpringerClient(empty_config).search(), [])

        limit_config = self._config(discovery_strategy="precise", pages_to_retrieve=2, results_per_page=1)
        payload = {
            "records": [
                {
                    "title": "Springer Survey",
                    "creators": [{"creator": "Ada Lovelace"}],
                    "publicationDate": "2024-01-01",
                    "publicationName": "AI Journal",
                    "doi": "10.1000/springer",
                }
            ]
        }
        with patch("discovery.springer_client.request_json", side_effect=[payload, payload]):
            results = SpringerClient(limit_config).search()

        self.assertEqual(len(results), limit_config.per_source_limit)

    def test_parse_record_handles_creator_variants_and_identifier_fallback(self) -> None:
        config = self._config()
        client = SpringerClient(config)

        paper = client._parse_record(
            {
                "title": "Structured Springer Record",
                "creators": [{"creator": "Ada Lovelace"}, "Grace Hopper"],
                "abstract": "<jats:p>Tagged abstract</jats:p>",
                "publicationDate": "2025-06-01",
                "publicationTitle": "Conference Proceedings",
                "identifier": "springer-id-1",
                "openaccess": "false",
                "url": [{"format": "application/pdf", "value": "https://example.org/paper.pdf"}],
            }
        )

        self.assertEqual(paper.authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(paper.abstract, "Tagged abstract")
        self.assertEqual(paper.year, 2025)
        self.assertEqual(paper.venue, "Conference Proceedings")
        self.assertEqual(paper.doi, "springer-id-1")
        self.assertTrue(paper.open_access)
        self.assertEqual(paper.external_ids["springer_identifier"], "springer-id-1")


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
