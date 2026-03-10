"""Tests for configuration validation, CLI parsing, and config-file loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import ResearchConfig, build_arg_parser, parse_analysis_pass


class ConfigTests(unittest.TestCase):
    """Exercise the configuration layer's normalization and parsing behavior."""

    def test_finalize_creates_query_key_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI literature reviews",
                search_keywords=["llm", "screening"],
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "review.db",
            ).finalize()

            self.assertTrue(config.query_key)
            self.assertTrue((root / "data").exists())
            self.assertTrue((root / "papers").exists())
            self.assertTrue((root / "results").exists())

    def test_from_cli_can_load_complete_config_file(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--config-file", "tests/fixtures/offline_config.json"])

        with patch("builtins.input", side_effect=AssertionError("input should not be called")):
            config = ResearchConfig.from_cli(args)

        self.assertEqual(config.research_topic, "AI-assisted literature reviews")
        self.assertFalse(config.openalex_enabled)
        self.assertEqual(config.fixture_data_path, Path("tests/fixtures/offline_papers.json"))

    def test_parse_analysis_pass(self) -> None:
        analysis_pass = parse_analysis_pass("deep:heuristic:85:triage:12")

        self.assertEqual(analysis_pass.name, "deep")
        self.assertEqual(analysis_pass.llm_provider, "heuristic")
        self.assertEqual(analysis_pass.threshold, 85.0)
        self.assertEqual(analysis_pass.decision_mode, "triage")
        self.assertEqual(analysis_pass.maybe_threshold_margin, 12.0)

    def test_from_cli_reads_additional_source_flags(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--topic",
                "Evidence discovery",
                "--research-question",
                "Can multiple discovery sources be configured safely?",
                "--review-objective",
                "Compare source configuration options.",
                "--inclusion-criteria",
                "metadata available",
                "--exclusion-criteria",
                "none",
                "--banned-topics",
                "spam",
                "--excluded-title-terms",
                "correction;editorial;erratum",
                "--keywords",
                "llm,review",
                "--boolean",
                "AND",
                "--pages",
                "1",
                "--discovery-strategy",
                "broad",
                "--year-start",
                "2020",
                "--year-end",
                "2026",
                "--max-discovered-records",
                "250",
                "--min-discovered-records",
                "20",
                "--max-papers",
                "10",
                "--skip-discovery",
                "--citation-snowballing",
                "--threshold",
                "70",
                "--download-pdfs",
                "--pdf-download-mode",
                "relevant_only",
                "--no-analyze-full-text",
                "--springer-enabled",
                "--arxiv-enabled",
                "--no-include-pubmed",
                "--llm-provider",
                "huggingface_local",
                "--semantic-scholar-api-key",
                "sem-key",
                "--crossref-mailto",
                "carina@example.com",
                "--unpaywall-email",
                "carina@example.com",
                "--springer-api-key",
                "springer-key",
                "--openai-api-key",
                "openai-key",
                "--openai-model",
                "gpt-5.4",
                "--ollama-model",
                "gpt-oss:20b",
                "--ollama-api-key",
                "ollama-key",
                "--llm-temperature",
                "0.2",
                "--huggingface-model",
                "openai/gpt-oss-20b",
                "--huggingface-max-new-tokens",
                "512",
                "--google-scholar-import-path",
                "tests/fixtures/google_scholar_import.json",
                "--researchgate-import-path",
                "tests/fixtures/researchgate_import.csv",
                "--data-dir",
                "data/test_cli",
                "--papers-dir",
                "papers/test_cli",
                "--relevant-pdfs-dir",
                "papers/test_cli/relevant_keep",
                "--results-dir",
                "results/test_cli",
                "--database-path",
                "data/test_cli/review.db",
                "--log-http-requests",
                "--log-http-payloads",
                "--log-llm-prompts",
                "--log-llm-responses",
                "--log-screening-decisions",
                "--profile-name",
                "test-profile",
            ]
        )

        with patch("builtins.input", side_effect=AssertionError("input should not be called")):
            config = ResearchConfig.from_cli(args)

        self.assertTrue(config.springer_enabled)
        self.assertTrue(config.arxiv_enabled)
        self.assertEqual(config.llm_provider, "huggingface_local")
        self.assertEqual(config.api_settings.semantic_scholar_api_key, "sem-key")
        self.assertEqual(config.api_settings.crossref_mailto, "carina@example.com")
        self.assertEqual(config.api_settings.unpaywall_email, "carina@example.com")
        self.assertEqual(config.api_settings.springer_api_key, "springer-key")
        self.assertEqual(config.api_settings.openai_api_key, "openai-key")
        self.assertEqual(config.api_settings.openai_model, "gpt-5.4")
        self.assertEqual(config.api_settings.ollama_model, "gpt-oss:20b")
        self.assertEqual(config.api_settings.ollama_api_key, "ollama-key")
        self.assertEqual(config.api_settings.llm_temperature, 0.2)
        self.assertEqual(config.api_settings.huggingface_model, "openai/gpt-oss-20b")
        self.assertEqual(config.api_settings.huggingface_max_new_tokens, 512)
        self.assertEqual(config.discovery_strategy, "broad")
        self.assertEqual(config.max_discovered_records, 250)
        self.assertEqual(config.min_discovered_records, 20)
        self.assertTrue(config.skip_discovery)
        self.assertTrue(config.download_pdfs)
        self.assertEqual(config.pdf_download_mode, "relevant_only")
        self.assertTrue(config.log_http_requests)
        self.assertTrue(config.log_http_payloads)
        self.assertTrue(config.log_llm_prompts)
        self.assertTrue(config.log_llm_responses)
        self.assertTrue(config.log_screening_decisions)
        self.assertEqual(config.profile_name, "test-profile")
        self.assertEqual(config.excluded_title_terms, ["correction", "editorial", "erratum"])
        self.assertEqual(config.google_scholar_import_path, Path("tests/fixtures/google_scholar_import.json"))
        self.assertEqual(config.researchgate_import_path, Path("tests/fixtures/researchgate_import.csv"))
        self.assertEqual(config.relevant_pdfs_dir, Path("papers/test_cli/relevant_keep"))
        self.assertEqual(config.results_dir, Path("results/test_cli"))
