"""Tests for manual-import and fixture-based discovery clients."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import ResearchConfig
from discovery.fixture_client import FixtureDiscoveryClient
from discovery.manual_import_client import ManualImportClient
from models.paper import PaperMetadata


class ImportAndFixtureClientTests(unittest.TestCase):
    """Exercise local import modes and their edge cases."""

    def _config(self, root: Path, **overrides) -> ResearchConfig:
        payload = {
            "research_topic": "AI-assisted literature reviews",
            "search_keywords": ["llm", "screening"],
            "include_pubmed": False,
            "data_dir": root / "data",
            "papers_dir": root / "papers",
            "results_dir": root / "results",
            "database_path": root / "data" / "review.db",
        }
        payload.update(overrides)
        return ResearchConfig(**payload).finalize()

    def test_manual_import_client_supports_json_csv_and_truthy_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "manual.json"
            csv_path = root / "manual.csv"
            json_path.write_text(
                json.dumps(
                    [
                        {
                            "title": "JSON paper",
                            "authors": "Ada|Grace",
                            "year": "2024",
                            "open_access": "yes",
                        },
                        {"title": ""},
                    ]
                ),
                encoding="utf-8",
            )
            csv_path.write_text(
                "title,authors,year,open_access\nCSV paper,\"Alice; Bob\",2025,1\n",
                encoding="utf-8",
            )

            config = self._config(root, manual_source_path=json_path)
            json_results = ManualImportClient(config, path=json_path).search()
            csv_results = ManualImportClient(config, path=csv_path).search()

        self.assertEqual(len(json_results), 1)
        self.assertEqual(json_results[0].authors, ["Ada", "Grace"])
        self.assertTrue(json_results[0].open_access)
        self.assertEqual(len(csv_results), 1)
        self.assertEqual(csv_results[0].authors, ["Alice", "Bob"])

    def test_manual_import_client_validates_path_and_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            bad_json = root / "bad.json"
            bad_json.write_text(json.dumps({"title": "wrong"}), encoding="utf-8")

            with self.assertRaises(ValueError):
                ManualImportClient(config)
            with self.assertRaises(ValueError):
                ManualImportClient(config, path=bad_json)._load_rows()

    def test_fixture_client_search_and_link_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(
                json.dumps(
                    [
                        {
                            "title": "Paper A",
                            "source": "fixture",
                            "doi": "10.1000/a",
                            "references": ["10.1000/b"],
                            "citations": ["Paper B"],
                        },
                        {
                            "title": "Paper B",
                            "source": "fixture",
                            "doi": "10.1000/b",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            config = self._config(root, fixture_data_path=fixture_path)
            client = FixtureDiscoveryClient(config)

            search_results = client.search()
            references = client.fetch_references(PaperMetadata(title="Paper A", source="fixture", doi="10.1000/a"))
            citations = client.fetch_citations(PaperMetadata(title="Paper A", source="fixture", doi="10.1000/a"))
            missing = client.fetch_references(PaperMetadata(title="Missing", source="fixture"))

        self.assertEqual(len(search_results), 2)
        self.assertEqual(search_results[0].query_key, config.query_key)
        self.assertEqual(references[0].title, "Paper B")
        self.assertEqual(citations[0].title, "Paper B")
        self.assertEqual(missing, [])

    def test_fixture_client_rejects_non_list_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(json.dumps({"bad": "shape"}), encoding="utf-8")
            config = self._config(root, fixture_data_path=fixture_path)

            with self.assertRaises(ValueError):
                FixtureDiscoveryClient(config)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
