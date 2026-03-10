"""Tests for heuristic relevance scoring and hard-exclusion rules."""

from __future__ import annotations

import unittest

from models.paper import PaperMetadata

from analysis.relevance_scoring import RelevanceScorer
from config import ResearchConfig


class RelevanceScoringTests(unittest.TestCase):
    """Verify excluded-title handling and ordinary LLM survey scoring behavior."""

    def test_correction_titles_are_excluded_by_default(self) -> None:
        config = ResearchConfig(
            research_topic="Large language models",
            search_keywords=["large language models", "survey", "benchmark"],
            year_range_start=2023,
            year_range_end=2026,
            include_pubmed=False,
        ).finalize()
        scorer = RelevanceScorer(config)
        paper = PaperMetadata(
            title="Correction: A survey on augmenting knowledge graphs with large language models",
            abstract="This note corrects a previously published survey on LLM benchmarks.",
            year=2026,
            citation_count=12,
        )

        result = scorer.deep_score(paper, stage_one_decision="exclude")

        self.assertEqual(result.decision, "exclude")
        self.assertIn("correction", result.matched_excluded_title_terms)
        self.assertIn("non-target publication type", result.exclusion_reason)

    def test_regular_llm_survey_is_not_excluded_by_title_terms(self) -> None:
        config = ResearchConfig(
            research_topic="Large language models",
            search_keywords=["large language models", "survey", "benchmark"],
            year_range_start=2023,
            year_range_end=2026,
            relevance_threshold=45,
            decision_mode="triage",
            include_pubmed=False,
        ).finalize()
        scorer = RelevanceScorer(config)
        paper = PaperMetadata(
            title="A survey on large language model based autonomous agents",
            abstract="We present a systematic review of LLM-based autonomous agents and evaluation strategies.",
            year=2024,
            citation_count=100,
        )

        result = scorer.deep_score(paper, stage_one_decision="maybe")

        self.assertEqual(result.matched_excluded_title_terms, [])
        self.assertFalse(scorer.has_hard_exclusion(paper))
        self.assertIn(result.decision, {"include", "maybe"})


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
