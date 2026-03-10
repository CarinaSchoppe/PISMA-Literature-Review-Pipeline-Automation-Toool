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
                "analysis_passes": "fast|huggingface_local|72|strict|8|Qwen/Qwen3-14B|0\ndeep|openai_compatible|85|triage|12|gpt-5.4|70",
                "llm_temperature": "0.25",
                "huggingface_model": "Qwen/Qwen3-14B",
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
        self.assertEqual(len(config.analysis_passes), 2)
        self.assertEqual(config.analysis_passes[0].model_name, "Qwen/Qwen3-14B")
        self.assertEqual(config.analysis_passes[1].model_name, "gpt-5.4")
        self.assertEqual(config.analysis_passes[1].min_input_score, 70.0)
        self.assertEqual(config.api_settings.llm_temperature, 0.25)
        self.assertEqual(config.api_settings.huggingface_model, "Qwen/Qwen3-14B")
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
            include_pubmed=False,
        ).finalize()

        values = config_to_form_values(config)

        self.assertEqual(values["research_topic"], "Systematic reviews")
        self.assertEqual(values["search_keywords"], "llm, screening")
        self.assertEqual(values["max_discovered_records"], 75)
        self.assertEqual(values["min_discovered_records"], 5)
        self.assertIn("Qwen/Qwen3-14B", values["analysis_passes"])

    def test_config_payload_to_form_values_accepts_saved_json_shape(self) -> None:
        payload = {
            "research_topic": "Systematic reviews",
            "search_keywords": ["llm", "screening"],
            "discovery_strategy": "broad",
            "max_discovered_records": 80,
            "min_discovered_records": 4,
            "api_settings": {"huggingface_model": "Qwen/Qwen3-14B"},
        }

        values = config_payload_to_form_values(payload)

        self.assertEqual(values["research_topic"], "Systematic reviews")
        self.assertEqual(values["search_keywords"], "llm, screening")
        self.assertEqual(values["discovery_strategy"], "broad")
        self.assertEqual(values["max_discovered_records"], 80)
        self.assertEqual(values["min_discovered_records"], 4)

    def test_default_form_values_cover_all_runtime_config_fields(self) -> None:
        values = default_form_values()
        covered_fields = set(values.keys())
        config_fields = set(ResearchConfig.model_fields.keys()) - {"api_settings", "query_key"}
        api_fields = set(ApiSettings.model_fields.keys())

        self.assertTrue(config_fields.issubset(covered_fields))
        self.assertTrue(api_fields.issubset(covered_fields))


if __name__ == "__main__":
    unittest.main()
