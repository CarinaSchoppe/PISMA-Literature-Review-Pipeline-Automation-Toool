"""Tests for configuration validation, CLI parsing, and config-file loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import AnalysisPassConfig, ResearchConfig, build_arg_parser, parse_analysis_pass


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

    def test_parse_analysis_pass_supports_extended_gui_format(self) -> None:
        analysis_pass = parse_analysis_pass("deep|huggingface_local|85|triage|12|Qwen/Qwen3-14B|70")

        self.assertEqual(analysis_pass.name, "deep")
        self.assertEqual(analysis_pass.llm_provider, "huggingface_local")
        self.assertEqual(analysis_pass.threshold, 85.0)
        self.assertEqual(analysis_pass.decision_mode, "triage")
        self.assertEqual(analysis_pass.maybe_threshold_margin, 12.0)
        self.assertEqual(analysis_pass.model_name, "Qwen/Qwen3-14B")
        self.assertEqual(analysis_pass.min_input_score, 70.0)

    def test_validation_rejects_negative_retry_and_worker_values(self) -> None:
        with self.assertRaises(ValueError):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], http_retry_base_delay_seconds=-1)
        with self.assertRaises(ValueError):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], discovery_workers=-1)
        with self.assertRaises(ValueError):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], google_scholar_pages=101)

    def test_google_scholar_page_bounds_are_configurable_and_validated_together(self) -> None:
        config = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            google_scholar_pages=12,
            google_scholar_page_min=5,
            google_scholar_page_max=25,
        )

        self.assertEqual(config.google_scholar_pages, 12)
        self.assertEqual(config.google_scholar_page_min, 5)
        self.assertEqual(config.google_scholar_page_max, 25)

        with self.assertRaises(ValueError):
            ResearchConfig(
                research_topic="Topic",
                search_keywords=["llm"],
                google_scholar_pages=4,
                google_scholar_page_min=5,
                google_scholar_page_max=25,
            )
        with self.assertRaises(ValueError):
            ResearchConfig(
                research_topic="Topic",
                search_keywords=["llm"],
                google_scholar_pages=10,
                google_scholar_page_min=15,
                google_scholar_page_max=10,
            )
        with self.assertRaisesRegex(ValueError, "Configuration value must be at least 1"):
            ResearchConfig(
                research_topic="Topic",
                search_keywords=["llm"],
                google_scholar_pages=1,
                google_scholar_page_min=0,
                google_scholar_page_max=10,
            )

    def test_model_validators_cover_non_dict_input_and_invalid_verbosity(self) -> None:
        validated = ResearchConfig.populate_google_scholar_page_defaults(["not-a-dict"])
        self.assertEqual(validated, ["not-a-dict"])

        with self.assertRaisesRegex(ValueError, "verbosity must be one of normal, verbose, or ultra_verbose"):
            ResearchConfig(
                research_topic="Topic",
                search_keywords=["llm"],
                verbosity="impossible",
            )

    def test_parse_analysis_pass_accepts_json_object_and_config_file_defaults_full_text_flag(self) -> None:
        analysis_pass = parse_analysis_pass(
            '{"name": "deep", "llm_provider": "gemini", "threshold": 81, "decision_mode": "triage"}'
        )
        self.assertEqual(analysis_pass, AnalysisPassConfig(name="deep", llm_provider="gemini", threshold=81, decision_mode="triage"))

        parser = build_arg_parser()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                (
                    '{"research_topic":"Topic","search_keywords":["llm"],'
                    '"boolean_operators":"AND","pages_to_retrieve":1,"year_range_start":2020,"year_range_end":2026,'
                    '"max_papers_to_analyze":5,"citation_snowballing_enabled":false,"relevance_threshold":70,'
                    '"download_pdfs":false,"include_pubmed":false}'
                ),
                encoding="utf-8",
            )
            args = parser.parse_args(["--config-file", str(config_path)])
            config = ResearchConfig.from_cli(args)
            self.assertFalse(config.analyze_full_text)

    def test_cli_runtime_destinations_align_with_ui_form_fields(self) -> None:
        from ui.view_model import default_form_values

        parser = build_arg_parser()
        form_fields = set(default_form_values())
        allowed_non_runtime = {"help", "config_file", "ui", "wizard", "verbose_flag", "ultra_verbose"}
        parser_dests = {
            action.dest
            for action in parser._actions
            if action.option_strings and action.dest not in allowed_non_runtime
        }

        self.assertTrue(parser_dests.issubset(form_fields))

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
                "--europe-pmc-enabled",
                "--core-enabled",
                "--no-include-pubmed",
                "--llm-provider",
                "huggingface_local",
                "--analysis-pass",
                "deep|ollama|85|triage|12|gpt-oss:20b|70",
                "--semantic-scholar-api-key",
                "sem-key",
                "--crossref-mailto",
                "carina@example.com",
                "--unpaywall-email",
                "carina@example.com",
                "--springer-api-key",
                "springer-key",
                "--core-api-key",
                "core-key",
                "--openai-api-key",
                "openai-key",
                "--openai-model",
                "gpt-5.4",
                "--openalex-calls-per-second",
                "4.5",
                "--semantic-scholar-calls-per-second",
                "1.5",
                "--semantic-scholar-max-requests-per-minute",
                "60",
                "--semantic-scholar-request-delay-seconds",
                "1.25",
                "--semantic-scholar-retry-attempts",
                "6",
                "--semantic-scholar-retry-backoff-strategy",
                "linear",
                "--semantic-scholar-retry-backoff-base-seconds",
                "3.5",
                "--crossref-calls-per-second",
                "2.0",
                "--springer-calls-per-second",
                "0.8",
                "--arxiv-calls-per-second",
                "0.25",
                "--pubmed-calls-per-second",
                "2.8",
                "--europe-pmc-calls-per-second",
                "1.8",
                "--core-calls-per-second",
                "1.2",
                "--unpaywall-calls-per-second",
                "1.2",
                "--gemini-api-key",
                "gemini-key",
                "--gemini-base-url",
                "https://generativelanguage.googleapis.com/v1beta",
                "--gemini-model",
                "gemini-2.5-flash",
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
                "--max-workers",
                "6",
                "--discovery-workers",
                "2",
                "--io-workers",
                "3",
                "--screening-workers",
                "4",
                "--partial-rerun-mode",
                "screening_and_reporting",
                "--incremental-report-regeneration",
                "--enable-async-network-stages",
                "--http-cache-enabled",
                "--http-cache-dir",
                "data/test_cli/http_cache",
                "--http-cache-ttl-seconds",
                "7200",
                "--http-retry-max-attempts",
                "6",
                "--http-retry-base-delay-seconds",
                "1.5",
                "--http-retry-max-delay-seconds",
                "45",
                "--pdf-batch-size",
                "8",
                "--reset-query-records",
                "--clear-screening-cache",
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
        self.assertTrue(config.europe_pmc_enabled)
        self.assertTrue(config.core_enabled)
        self.assertEqual(config.llm_provider, "huggingface_local")
        self.assertEqual(config.api_settings.semantic_scholar_api_key, "sem-key")
        self.assertEqual(config.api_settings.crossref_mailto, "carina@example.com")
        self.assertEqual(config.api_settings.unpaywall_email, "carina@example.com")
        self.assertEqual(config.api_settings.springer_api_key, "springer-key")
        self.assertEqual(config.api_settings.core_api_key, "core-key")
        self.assertEqual(config.api_settings.openai_api_key, "openai-key")
        self.assertEqual(config.api_settings.openai_model, "gpt-5.4")
        self.assertEqual(config.api_settings.openalex_calls_per_second, 4.5)
        self.assertEqual(config.api_settings.semantic_scholar_calls_per_second, 1.5)
        self.assertEqual(config.api_settings.semantic_scholar_max_requests_per_minute, 60)
        self.assertEqual(config.api_settings.semantic_scholar_request_delay_seconds, 1.25)
        self.assertEqual(config.api_settings.semantic_scholar_retry_attempts, 6)
        self.assertEqual(config.api_settings.semantic_scholar_retry_backoff_strategy, "linear")
        self.assertEqual(config.api_settings.semantic_scholar_retry_backoff_base_seconds, 3.5)
        self.assertEqual(config.api_settings.crossref_calls_per_second, 2.0)
        self.assertEqual(config.api_settings.springer_calls_per_second, 0.8)
        self.assertEqual(config.api_settings.arxiv_calls_per_second, 0.25)
        self.assertEqual(config.api_settings.pubmed_calls_per_second, 2.8)
        self.assertEqual(config.api_settings.europe_pmc_calls_per_second, 1.8)
        self.assertEqual(config.api_settings.core_calls_per_second, 1.2)
        self.assertEqual(config.api_settings.unpaywall_calls_per_second, 1.2)
        self.assertEqual(config.api_settings.gemini_api_key, "gemini-key")
        self.assertEqual(config.api_settings.gemini_base_url, "https://generativelanguage.googleapis.com/v1beta")
        self.assertEqual(config.api_settings.gemini_model, "gemini-2.5-flash")
        self.assertEqual(config.api_settings.ollama_model, "gpt-oss:20b")
        self.assertEqual(config.api_settings.ollama_api_key, "ollama-key")
        self.assertEqual(config.api_settings.llm_temperature, 0.2)
        self.assertEqual(config.api_settings.huggingface_model, "openai/gpt-oss-20b")
        self.assertEqual(config.api_settings.huggingface_max_new_tokens, 512)
        self.assertEqual(config.discovery_strategy, "broad")
        self.assertEqual(config.max_discovered_records, 250)
        self.assertEqual(config.min_discovered_records, 20)
        self.assertTrue(config.skip_discovery)
        self.assertEqual(config.max_workers, 6)
        self.assertEqual(config.discovery_workers, 2)
        self.assertEqual(config.io_workers, 3)
        self.assertEqual(config.screening_workers, 4)
        self.assertEqual(config.partial_rerun_mode, "screening_and_reporting")
        self.assertTrue(config.incremental_report_regeneration)
        self.assertTrue(config.enable_async_network_stages)
        self.assertTrue(config.http_cache_enabled)
        self.assertEqual(config.http_cache_dir, Path("data/test_cli/http_cache"))
        self.assertEqual(config.http_cache_ttl_seconds, 7200)
        self.assertEqual(config.http_retry_max_attempts, 6)
        self.assertEqual(config.http_retry_base_delay_seconds, 1.5)
        self.assertEqual(config.http_retry_max_delay_seconds, 45.0)
        self.assertEqual(config.pdf_batch_size, 8)
        self.assertTrue(config.reset_query_records)
        self.assertTrue(config.clear_screening_cache)
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
        self.assertEqual(len(config.analysis_passes), 1)
        self.assertEqual(config.analysis_passes[0].model_name, "gpt-oss:20b")
        self.assertEqual(config.analysis_passes[0].min_input_score, 70.0)

    def test_cli_parses_google_scholar_page_depth_controls(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--topic",
                "AI governance",
                "--research-question",
                "How relevant are the discovered papers to AI governance?",
                "--review-objective",
                "Collect governance-focused literature.",
                "--keywords",
                "llm,policy",
                "--boolean",
                "AND",
                "--inclusion-criteria",
                "governance",
                "--exclusion-criteria",
                "none",
                "--banned-topics",
                "spam",
                "--excluded-title-terms",
                "correction;erratum;editorial;retraction",
                "--pages",
                "1",
                "--year-start",
                "2020",
                "--year-end",
                "2026",
                "--max-papers",
                "5",
                "--citation-snowballing",
                "--threshold",
                "70",
                "--no-download-pdfs",
                "--no-analyze-full-text",
                "--google-scholar-enabled",
                "--google-scholar-pages",
                "7",
                "--google-scholar-page-min",
                "2",
                "--google-scholar-page-max",
                "20",
                "--google-scholar-results-per-page",
                "15",
                "--no-include-pubmed",
            ]
        )

        with patch("builtins.input", side_effect=AssertionError("input should not be called")):
            config = ResearchConfig.from_cli(args)

        self.assertTrue(config.google_scholar_enabled)
        self.assertEqual(config.google_scholar_pages, 7)
        self.assertEqual(config.google_scholar_page_min, 2)
        self.assertEqual(config.google_scholar_page_max, 20)
        self.assertEqual(config.google_scholar_results_per_page, 15)

    def test_cli_parses_persisted_ui_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--topic",
                "AI governance",
                "--research-question",
                "How should the UI open?",
                "--review-objective",
                "Verify GUI defaults",
                "--keywords",
                "llm, policy",
                "--inclusion-criteria",
                "governance focus",
                "--exclusion-criteria",
                "none",
                "--banned-topics",
                "spam",
                "--excluded-title-terms",
                "correction;erratum;editorial;retraction",
                "--boolean",
                "AND",
                "--pages",
                "1",
                "--threshold",
                "70",
                "--no-download-pdfs",
                "--no-analyze-full-text",
                "--citation-snowballing",
                "--no-include-pubmed",
                "--llm-provider",
                "auto",
                "--decision-mode",
                "strict",
                "--run-mode",
                "analyze",
                "--verbosity",
                "verbose",
                "--max-papers",
                "5",
                "--year-start",
                "2020",
                "--year-end",
                "2026",
                "--ui-settings-mode",
                "advanced",
                "--ui-show-advanced-settings",
            ]
        )

        with patch("builtins.input", side_effect=AssertionError("input should not be called")):
            config = ResearchConfig.from_cli(args)

        self.assertEqual(config.ui_settings_mode, "advanced")
        self.assertTrue(config.ui_show_advanced_settings)

    def test_config_properties_cover_query_variants_screening_brief_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="Biomedical LLM review",
                research_question="How are LLMs used in clinical screening?",
                review_objective="Map methods and benchmarks.",
                inclusion_criteria=["clinical", "llm"],
                exclusion_criteria=["non-medical"],
                banned_topics=["agriculture"],
                search_keywords=["llm", "clinical", "screening"],
                discovery_strategy="broad",
                llm_provider="heuristic",
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "review.db",
            ).finalize()

            self.assertTrue(config.include_pubmed)
            self.assertGreaterEqual(len(config.discovery_queries), 3)
            self.assertIn("Research topic:", config.screening_brief)
            self.assertTrue(config.screening_context_key)
            snapshot = config.save_snapshot()

            self.assertTrue(snapshot.exists())
            self.assertIn("run_config.json", str(snapshot))

    def test_resolved_analysis_passes_fallback_and_explicit_chain(self) -> None:
        default_config = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            llm_provider="heuristic",
            relevance_threshold=77,
            decision_mode="triage",
            maybe_threshold_margin=9,
        ).finalize()
        explicit_config = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            run_mode="analyze",
            analysis_passes=[
                AnalysisPassConfig(
                    name="fast",
                    llm_provider="huggingface_local",
                    threshold=65,
                    decision_mode="strict",
                    maybe_threshold_margin=5,
                    model_name="Qwen/Qwen3-14B",
                    min_input_score=0,
                )
            ],
        ).finalize()

        default_passes = default_config.resolved_analysis_passes
        explicit_passes = explicit_config.resolved_analysis_passes

        self.assertEqual(len(default_passes), 1)
        self.assertEqual(default_passes[0].threshold, 77)
        self.assertEqual(default_passes[0].decision_mode, "triage")
        self.assertEqual(explicit_passes[0].model_name, "Qwen/Qwen3-14B")

    def test_from_cli_interactive_wizard_path(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        answers = iter(
            [
                "Interactive topic",
                "Interactive question",
                "Interactive objective",
                "llm, review",
                "include 1;include 2",
                "exclude 1",
                "banned 1",
                "correction;editorial",
                "AND",
                "2",
                "2019",
                "2026",
                "12",
                "yes",
                "70",
                "yes",
                "no",
                "yes",
                "auto",
                "strict",
                "analyze",
                "verbose",
            ]
        )

        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            config = ResearchConfig.from_cli(args)

        self.assertEqual(config.research_topic, "Interactive topic")
        self.assertEqual(config.search_keywords, ["llm", "review"])
        self.assertTrue(config.citation_snowballing_enabled)
        self.assertTrue(config.download_pdfs)
        self.assertFalse(config.analyze_full_text)
        self.assertEqual(config.verbosity, "normal")
