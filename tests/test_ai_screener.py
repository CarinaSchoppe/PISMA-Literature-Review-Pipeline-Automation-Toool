"""Tests for LLM-screening fallback behavior and structured parsing guards."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from models.paper import PaperMetadata

from analysis.ai_screener import AIScreener
from config import ResearchConfig


class _FakeEnabledLLMClient:
    """Enabled fake LLM client that returns configurable raw text responses."""

    enabled = True
    provider_name = "fake_llm"

    def __init__(self, responses: str | list[str | None]) -> None:
        if isinstance(responses, list):
            self.responses = list(responses)
        else:
            self.responses = [responses]
        self.calls: list[tuple[str, str]] = []

    def chat(self, *, system_prompt: str, user_prompt: str):  # noqa: ANN001
        self.calls.append((system_prompt, user_prompt))
        content = self.responses.pop(0) if self.responses else None
        return SimpleNamespace(content=content)


class AIScreenerTests(unittest.TestCase):
    """Verify that malformed LLM outputs do not overwrite heuristic screening results."""

    def _base_config(self, **overrides) -> ResearchConfig:
        return ResearchConfig(
            research_topic="AI-assisted literature reviews",
            search_keywords=["large language models", "screening", "systematic review"],
            include_pubmed=False,
            **overrides,
        ).finalize()

    def _paper(self, **overrides) -> PaperMetadata:
        payload = {
            "title": "Large language models for systematic review screening",
            "abstract": "We evaluate LLM support for systematic review screening workflows.",
            "year": 2024,
            "citation_count": 42,
            "raw_payload": {},
        }
        payload.update(overrides)
        return PaperMetadata(**payload)

    def test_hard_exclusion_short_circuits_before_any_llm_call(self) -> None:
        fake_client = _FakeEnabledLLMClient(['{"decision": "include"}'])
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper(title="Correction: Large language models for systematic review screening")

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            result = screener.screen(paper)

        self.assertEqual(result.stage_one_decision, "exclude")
        self.assertEqual(result.decision, "exclude")
        self.assertEqual(fake_client.calls, [])

    def test_heuristic_screening_path_matches_relevance_scorer(self) -> None:
        config = self._base_config(llm_provider="heuristic", relevance_threshold=50)
        paper = self._paper()

        screener = AIScreener(config)
        result = screener.screen(paper)
        expected = screener.scorer.deep_score(
            paper,
            stage_one_decision=screener.scorer.quick_screen(paper),
        )

        self.assertEqual(result.relevance_score, expected.relevance_score)
        self.assertEqual(result.decision, expected.decision)
        self.assertTrue(result.explanation)

    def test_invalid_stage_two_json_falls_back_to_heuristic_scoring(self) -> None:
        config = self._base_config(llm_provider="openai_compatible", relevance_threshold=50)
        paper = self._paper()

        with patch(
            "analysis.ai_screener.build_llm_client",
            return_value=_FakeEnabledLLMClient("This is not strict JSON."),
        ):
            screener = AIScreener(config)
            result = screener.screen(paper)
            expected = screener.scorer.deep_score(
                paper,
                stage_one_decision=screener.scorer.quick_screen(paper),
            )

        self.assertEqual(result.relevance_score, expected.relevance_score)
        self.assertEqual(result.decision, expected.decision)
        self.assertIn("Topic match", result.explanation)

    def test_llm_stage_one_exclude_skips_stage_two(self) -> None:
        fake_client = _FakeEnabledLLMClient(['{"decision": "exclude"}'])
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper()

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            result = screener.screen(paper)

        self.assertEqual(result.stage_one_decision, "exclude")
        self.assertEqual(result.decision, "exclude")
        self.assertEqual(len(fake_client.calls), 1)

    def test_llm_stage_two_valid_json_is_returned_directly(self) -> None:
        fake_client = _FakeEnabledLLMClient(
            [
                '{"decision": "include"}',
                (
                    '{"relevance_score": 88, "explanation": "Strong topical match", '
                    '"extracted_passage": "Key sentence", "methodology_category": "survey", '
                    '"domain_category": "ai", "decision": "include", "retain_reason": "Fits scope", '
                    '"exclusion_reason": "", "matched_inclusion_criteria": ["llm"], '
                    '"matched_exclusion_criteria": [], "matched_banned_topics": [], '
                    '"matched_excluded_title_terms": []}'
                ),
            ]
        )
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper(raw_payload={"full_text_excerpt": "Useful full text context."})

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            result = screener.screen(paper)

        self.assertEqual(result.decision, "include")
        self.assertEqual(result.relevance_score, 88.0)
        self.assertEqual(result.methodology_category, "survey")
        self.assertEqual(result.matched_inclusion_criteria, ["llm"])
        self.assertEqual(result.retain_reason, "Fits scope")

    def test_llm_stage_two_invalid_decision_or_missing_score_falls_back(self) -> None:
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper()

        for stage_two_response in [
            '{"decision": "keep", "relevance_score": 90}',
            '{"decision": "include"}',
        ]:
            with self.subTest(stage_two_response=stage_two_response):
                fake_client = _FakeEnabledLLMClient(['{"decision": "include"}', stage_two_response])
                with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
                    screener = AIScreener(config)
                    result = screener.screen(paper)
                    expected = screener.scorer.deep_score(paper, stage_one_decision="include")
                self.assertEqual(result.decision, expected.decision)
                self.assertEqual(result.relevance_score, expected.relevance_score)

    def test_llm_stage_two_parse_exception_returns_none(self) -> None:
        config = self._base_config(llm_provider="openai_compatible")
        fake_client = _FakeEnabledLLMClient(['{"decision":"include"}'])
        paper = self._paper()

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            with patch.object(
                screener,
                "_chat_completion",
                return_value='{"decision":"include","relevance_score":88,"explanation":"ok"}',
            ), patch("analysis.ai_screener.ScreeningResult", side_effect=ValueError("bad payload")):
                result = screener._llm_stage_two(paper, "include")

        self.assertIsNone(result)

    def test_summarize_review_returns_none_without_llm_or_without_papers(self) -> None:
        config = self._base_config(llm_provider="heuristic")
        screener = AIScreener(config)

        self.assertIsNone(screener.summarize_review([]))
        self.assertIsNone(screener.summarize_review([self._paper()]))

    def test_summarize_review_uses_llm_when_available(self) -> None:
        fake_client = _FakeEnabledLLMClient("# Review summary")
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper(
            raw_payload={"full_text_excerpt": "Long excerpt"},
            methodology_category="survey",
            domain_category="healthcare",
            relevance_score=91,
            inclusion_decision="include",
        )

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            summary = screener.summarize_review([paper])

        self.assertEqual(summary, "# Review summary")
        self.assertEqual(len(fake_client.calls), 1)
        self.assertIn("Theme Overview", fake_client.calls[0][1])
        self.assertIn("Research topic:", fake_client.calls[0][1])

    def test_parse_json_response_handles_fenced_and_invalid_payloads(self) -> None:
        config = self._base_config(llm_provider="heuristic")
        screener = AIScreener(config)

        fenced = screener._parse_json_response("```json\n{\"decision\": \"include\"}\n```")
        invalid = screener._parse_json_response("not json")
        malformed = screener._parse_json_response("{not valid json}")

        self.assertEqual(fenced["decision"], "include")
        self.assertEqual(invalid, {})
        self.assertEqual(malformed, {})

    def test_chat_completion_returns_none_when_client_has_no_content(self) -> None:
        fake_client = _FakeEnabledLLMClient([None])
        config = self._base_config(llm_provider="openai_compatible", verbosity="debug")

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            content = screener._chat_completion(system_prompt="system", user_prompt="user")

        self.assertIsNone(content)

    def test_stage_one_and_stage_two_return_none_when_llm_returns_no_content(self) -> None:
        fake_client = _FakeEnabledLLMClient([None, None])
        config = self._base_config(llm_provider="openai_compatible")
        paper = self._paper()

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            self.assertIsNone(screener._llm_stage_one(paper))
            self.assertIsNone(screener._llm_stage_two(paper, "include"))

    def test_stage_one_invalid_decision_returns_none_and_verbose_logs_are_supported(self) -> None:
        fake_client = _FakeEnabledLLMClient(['{"decision":"unknown"}', '{"decision":"maybe"}'])
        config = self._base_config(llm_provider="openai_compatible", verbosity="verbose")
        paper = self._paper()

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            self.assertIsNone(screener._llm_stage_one(paper))
            result = screener.screen(paper)

        self.assertIn(result.decision, {"include", "maybe", "exclude"})


if __name__ == "__main__":
    unittest.main()
