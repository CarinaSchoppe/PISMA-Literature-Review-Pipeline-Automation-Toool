"""Tests for the mapping between the guided UI form and the runtime config model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import ApiSettings, ResearchConfig
from ui.view_model import (
    ProfileManager,
    config_payload_to_form_values,
    config_to_form_values,
    default_form_values,
    form_values_to_config,
)


class UIViewModelTests(unittest.TestCase):
    """Verify UI defaults, profile persistence, and config round-tripping."""

    def test_form_values_round_trip_into_research_config(self) -> None:
        values = default_form_values()
        values.update(
            {
                "research_topic": "AI-assisted reviews",
                "search_keywords": "llm, screening, evidence synthesis",
                "discovery_strategy": "broad",
                "max_discovered_records": "120",
                "min_discovered_records": "10",
                "skip_discovery": True,
                "discovery_workers": 2,
                "io_workers": 3,
                "screening_workers": 4,
                "partial_rerun_mode": "screening_and_reporting",
                "incremental_report_regeneration": True,
                "enable_async_network_stages": True,
                "http_cache_enabled": True,
                "http_cache_dir": "data/http_cache",
                "http_cache_ttl_seconds": "7200",
                "http_retry_max_attempts": "6",
                "http_retry_base_delay_seconds": "1.5",
                "http_retry_max_delay_seconds": "45",
                "pdf_batch_size": "8",
                "reset_query_records": True,
                "clear_screening_cache": True,
                "analysis_passes": "fast|huggingface_local|72|strict|8|Qwen/Qwen3-14B|0\ndeep|openai_compatible|85|triage|12|gpt-5.4|70",
                "llm_temperature": "0.25",
                "openalex_calls_per_second": "4.5",
                "semantic_scholar_calls_per_second": "1.5",
                "semantic_scholar_max_requests_per_minute": "60",
                "semantic_scholar_request_delay_seconds": "1.25",
                "semantic_scholar_retry_attempts": "6",
                "semantic_scholar_retry_backoff_strategy": "linear",
                "semantic_scholar_retry_backoff_base_seconds": "3.5",
                "crossref_calls_per_second": "2.0",
                "springer_calls_per_second": "0.8",
                "arxiv_calls_per_second": "0.25",
                "pubmed_calls_per_second": "2.8",
                "europe_pmc_calls_per_second": "1.8",
                "core_calls_per_second": "1.2",
                "unpaywall_calls_per_second": "1.2",
                "huggingface_model": "Qwen/Qwen3-14B",
                "gemini_model": "gemini-2.5-flash",
                "gemini_api_key": "gem-key",
                "core_api_key": "core-key",
                "europe_pmc_enabled": True,
                "core_enabled": True,
                "log_http_requests": True,
                "log_screening_decisions": True,
            }
        )

        config = form_values_to_config(values)

        self.assertEqual(config.research_topic, "AI-assisted reviews")
        self.assertEqual(config.search_keywords, ["llm", "screening", "evidence synthesis"])
        self.assertEqual(config.discovery_strategy, "broad")
        self.assertEqual(config.max_discovered_records, 120)
        self.assertEqual(config.min_discovered_records, 10)
        self.assertTrue(config.skip_discovery)
        self.assertEqual(config.discovery_workers, 2)
        self.assertEqual(config.io_workers, 3)
        self.assertEqual(config.screening_workers, 4)
        self.assertEqual(config.partial_rerun_mode, "screening_and_reporting")
        self.assertTrue(config.incremental_report_regeneration)
        self.assertTrue(config.enable_async_network_stages)
        self.assertTrue(config.http_cache_enabled)
        self.assertEqual(config.http_cache_dir, Path("data/http_cache"))
        self.assertEqual(config.http_cache_ttl_seconds, 7200)
        self.assertEqual(config.http_retry_max_attempts, 6)
        self.assertEqual(config.http_retry_base_delay_seconds, 1.5)
        self.assertEqual(config.http_retry_max_delay_seconds, 45.0)
        self.assertEqual(config.pdf_batch_size, 8)
        self.assertTrue(config.reset_query_records)
        self.assertTrue(config.clear_screening_cache)
        self.assertEqual(len(config.analysis_passes), 2)
        self.assertEqual(config.analysis_passes[0].model_name, "Qwen/Qwen3-14B")
        self.assertEqual(config.analysis_passes[1].model_name, "gpt-5.4")
        self.assertEqual(config.analysis_passes[1].min_input_score, 70.0)
        self.assertEqual(config.api_settings.llm_temperature, 0.25)
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
        self.assertEqual(config.api_settings.huggingface_model, "Qwen/Qwen3-14B")
        self.assertEqual(config.api_settings.gemini_model, "gemini-2.5-flash")
        self.assertEqual(config.api_settings.gemini_api_key, "gem-key")
        self.assertEqual(config.api_settings.core_api_key, "core-key")
        self.assertTrue(config.europe_pmc_enabled)
        self.assertTrue(config.core_enabled)
        self.assertTrue(config.log_http_requests)
        self.assertTrue(config.log_screening_decisions)

    def test_profile_manager_round_trips_json_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ProfileManager(Path(temp_dir))
            values = default_form_values()
            values.update(
                {
                    "research_topic": "Evidence discovery",
                    "search_keywords": "llm, review",
                    "profile_name": "demo-profile",
                    "results_dir": "results/demo-profile",
                }
            )

            path = manager.save_profile("demo-profile", values)
            loaded = manager.load_profile("demo-profile")

            self.assertTrue(path.exists())
            self.assertEqual(loaded["research_topic"], "Evidence discovery")
            self.assertEqual(loaded["profile_name"], "demo-profile")
            self.assertEqual(Path(loaded["results_dir"]), Path("results/demo-profile"))

    def test_config_to_form_values_flattens_validated_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="Systematic reviews",
                search_keywords=["llm", "screening"],
                discovery_strategy="balanced",
                max_discovered_records=75,
                min_discovered_records=5,
                analysis_passes=[
                    {
                        "name": "fast",
                        "llm_provider": "huggingface_local",
                        "threshold": 72,
                        "decision_mode": "strict",
                        "maybe_threshold_margin": 8,
                        "model_name": "Qwen/Qwen3-14B",
                        "min_input_score": 0,
                    }
                ],
                discovery_workers=2,
                io_workers=3,
                screening_workers=4,
                partial_rerun_mode="screening_and_reporting",
                incremental_report_regeneration=True,
                enable_async_network_stages=True,
                http_cache_enabled=True,
                http_cache_dir=root / "data" / "http_cache",
                http_cache_ttl_seconds=7200,
                http_retry_max_attempts=6,
                http_retry_base_delay_seconds=1.5,
                http_retry_max_delay_seconds=45.0,
                pdf_batch_size=8,
                reset_query_records=True,
                clear_screening_cache=True,
                include_pubmed=False,
                europe_pmc_enabled=True,
                core_enabled=True,
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
                api_settings={"core_api_key": "core-key"},
            ).finalize()

            values = config_to_form_values(config)

            self.assertEqual(values["research_topic"], "Systematic reviews")
            self.assertEqual(values["search_keywords"], "llm, screening")
            self.assertEqual(values["max_discovered_records"], 75)
            self.assertEqual(values["min_discovered_records"], 5)
            self.assertEqual(values["discovery_workers"], 2)
            self.assertEqual(values["io_workers"], 3)
            self.assertEqual(values["screening_workers"], 4)
            self.assertEqual(values["partial_rerun_mode"], "screening_and_reporting")
            self.assertTrue(values["incremental_report_regeneration"])
            self.assertTrue(values["enable_async_network_stages"])
            self.assertTrue(values["http_cache_enabled"])
            self.assertEqual(values["http_cache_dir"], (root / "data" / "http_cache").as_posix())
            self.assertEqual(values["http_cache_ttl_seconds"], 7200)
            self.assertEqual(values["http_retry_max_attempts"], 6)
            self.assertEqual(values["http_retry_base_delay_seconds"], 1.5)
            self.assertEqual(values["http_retry_max_delay_seconds"], 45.0)
            self.assertEqual(values["pdf_batch_size"], 8)
            self.assertEqual(values["core_api_key"], "core-key")
            self.assertTrue(values["reset_query_records"])
            self.assertTrue(values["clear_screening_cache"])
            self.assertEqual(values["semantic_scholar_max_requests_per_minute"], 120)
            self.assertEqual(values["semantic_scholar_request_delay_seconds"], 0.0)
            self.assertEqual(values["semantic_scholar_retry_attempts"], 4)
            self.assertEqual(values["semantic_scholar_retry_backoff_strategy"], "exponential")
            self.assertEqual(values["semantic_scholar_retry_backoff_base_seconds"], 2.0)
            self.assertIn("Qwen/Qwen3-14B", values["analysis_passes"])
            self.assertTrue(values["europe_pmc_enabled"])
            self.assertTrue(values["core_enabled"])

    def test_config_payload_to_form_values_accepts_saved_json_shape(self) -> None:
        payload = {
            "research_topic": "Systematic reviews",
            "search_keywords": ["llm", "screening"],
            "discovery_strategy": "broad",
            "max_discovered_records": 80,
            "min_discovered_records": 4,
            "discovery_workers": 2,
            "io_workers": 3,
            "screening_workers": 4,
            "partial_rerun_mode": "screening_and_reporting",
            "incremental_report_regeneration": True,
            "enable_async_network_stages": True,
            "http_cache_enabled": True,
            "http_cache_dir": "data/http_cache",
            "http_cache_ttl_seconds": 7200,
            "http_retry_max_attempts": 6,
            "http_retry_base_delay_seconds": 1.5,
            "http_retry_max_delay_seconds": 45.0,
            "pdf_batch_size": 8,
            "api_settings": {
                "huggingface_model": "Qwen/Qwen3-14B",
                "gemini_model": "gemini-2.5-flash",
                "openalex_calls_per_second": 4.5,
                "core_api_key": "core-key",
                "europe_pmc_calls_per_second": 1.8,
                "core_calls_per_second": 1.2,
            },
            "europe_pmc_enabled": True,
            "core_enabled": True,
        }

        values = config_payload_to_form_values(payload)

        self.assertEqual(values["research_topic"], "Systematic reviews")
        self.assertEqual(values["search_keywords"], "llm, screening")
        self.assertEqual(values["discovery_strategy"], "broad")
        self.assertEqual(values["max_discovered_records"], 80)
        self.assertEqual(values["min_discovered_records"], 4)
        self.assertEqual(values["discovery_workers"], 2)
        self.assertEqual(values["io_workers"], 3)
        self.assertEqual(values["screening_workers"], 4)
        self.assertEqual(values["partial_rerun_mode"], "screening_and_reporting")
        self.assertTrue(values["incremental_report_regeneration"])
        self.assertTrue(values["enable_async_network_stages"])
        self.assertTrue(values["http_cache_enabled"])
        self.assertEqual(values["http_cache_dir"], "data/http_cache")
        self.assertEqual(values["http_cache_ttl_seconds"], 7200)
        self.assertEqual(values["http_retry_max_attempts"], 6)
        self.assertEqual(values["http_retry_base_delay_seconds"], 1.5)
        self.assertEqual(values["http_retry_max_delay_seconds"], 45.0)
        self.assertEqual(values["pdf_batch_size"], 8)
        self.assertEqual(values["gemini_model"], "gemini-2.5-flash")
        self.assertEqual(values["openalex_calls_per_second"], 4.5)
        self.assertEqual(values["core_api_key"], "core-key")
        self.assertEqual(values["europe_pmc_calls_per_second"], 1.8)
        self.assertEqual(values["core_calls_per_second"], 1.2)
        self.assertTrue(values["europe_pmc_enabled"])
        self.assertTrue(values["core_enabled"])

    def test_default_form_values_cover_all_runtime_config_fields(self) -> None:
        values = default_form_values()
        covered_fields = set(values.keys())
        config_fields = set(ResearchConfig.model_fields.keys()) - {"api_settings", "query_key"}
        api_fields = set(ApiSettings.model_fields.keys())

        self.assertTrue(config_fields.issubset(covered_fields))
        self.assertTrue(api_fields.issubset(covered_fields))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
