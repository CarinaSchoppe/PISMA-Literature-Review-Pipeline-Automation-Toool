"""Tests for the local semantic topic prefilter and MiniLM-style screening integration."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from analysis.ai_screener import AIScreener
from analysis.topic_prefilter import BaseTopicMatcher, LocalTopicMatcher, build_topic_matcher
from config import ResearchConfig
from models.paper import PaperMetadata


class _FakeTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class nn:
        class functional:
            @staticmethod
            def normalize(value, p=2, dim=1):  # noqa: ANN001, ARG004
                return value

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    def no_grad():
        return nullcontext()


class _FakeTokenizer:
    def __call__(self, texts, **kwargs):  # noqa: ANN001, ARG002
        return {"attention_mask": _FakeTensorBatch()}


class _FakeTensorBatch:
    def unsqueeze(self, value: int):  # noqa: ARG002
        return self

    def expand(self, _size):  # noqa: ANN001
        return self

    def float(self):
        return self

    def to(self, _device):  # noqa: ANN001
        return self


class _FakeModelOutput:
    last_hidden_state = _FakeTensorBatch()


class _FakeModel:
    def to(self, _device):  # noqa: ANN001
        return self

    def eval(self):
        return self

    def __call__(self, **kwargs):  # noqa: ANN003, ARG002
        return _FakeModelOutput()


class _FakeTokenizerLoader:
    @staticmethod
    def from_pretrained(*args, **kwargs):  # noqa: ANN002, ANN003
        if kwargs.get("trust_remote_code") is None:
            raise AssertionError("Expected trust_remote_code to be forwarded")
        return _FakeTokenizer()


class _FakeModelLoader:
    @staticmethod
    def from_pretrained(*args, **kwargs):  # noqa: ANN002, ANN003
        if kwargs.get("trust_remote_code") is None:
            raise AssertionError("Expected trust_remote_code to be forwarded")
        return _FakeModel()


class _FakeVector:
    def __init__(self, value: float) -> None:
        self.value = value

    def __mul__(self, other: "_FakeVector") -> "_FakeProduct":
        return _FakeProduct(self.value * other.value)


class _FakeProduct:
    def __init__(self, value: float) -> None:
        self.value = value

    def sum(self) -> "_FakeScalar":
        return _FakeScalar(self.value)


class _FakeScalar:
    def __init__(self, value: float) -> None:
        self.value = value

    def item(self) -> float:
        return self.value


class TopicPrefilterTests(unittest.TestCase):
    """Verify local semantic topic scoring, threshold mapping, and pipeline integration."""

    def _config(self, **overrides) -> ResearchConfig:
        return ResearchConfig(
            research_topic="AI governance for healthcare systems",
            research_question="How relevant are papers to AI governance in health?",
            review_objective="Retain papers focused on AI governance, evaluation, and deployment.",
            search_keywords=["AI governance", "healthcare AI", "deployment"],
            inclusion_criteria=["governance", "evaluation"],
            include_pubmed=False,
            **overrides,
        ).finalize()

    def _paper(self, **overrides) -> PaperMetadata:
        payload = {
            "title": "AI governance for hospital decision support",
            "abstract": "This paper evaluates governance and deployment choices for healthcare AI.",
            "source": "fixture",
            "raw_payload": {"keywords": ["AI governance", "deployment"]},
        }
        payload.update(overrides)
        return PaperMetadata(**payload)

    def test_build_topic_matcher_returns_disabled_matcher_when_prefilter_is_off(self) -> None:
        matcher = build_topic_matcher(self._config(topic_prefilter_enabled=False))

        self.assertIsInstance(matcher, BaseTopicMatcher)
        self.assertFalse(matcher.enabled)
        self.assertIsNone(matcher.score_paper(self._paper()))

    def test_local_topic_matcher_scores_high_relevance_and_tracks_used_sections(self) -> None:
        config = self._config(
            topic_prefilter_enabled=True,
            topic_prefilter_filter_low_relevance=True,
            topic_prefilter_text_mode="title_abstract_full_text",
        )
        paper = self._paper(raw_payload={"keywords": ["AI governance", "deployment"], "full_text_excerpt": "Detailed governance analysis for healthcare AI."})

        with patch("analysis.topic_prefilter.load_embedding_runtime", return_value=(_FakeTorch, _FakeTokenizerLoader, _FakeModelLoader)), \
                patch.object(LocalTopicMatcher, "_embed_texts", return_value=[_FakeVector(1.0), _FakeVector(0.82)]):
            matcher = LocalTopicMatcher(config)
            result = matcher.score_paper(paper)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(matcher.enabled)
        self.assertEqual(result.classification, "HIGH_RELEVANCE")
        self.assertFalse(result.should_exclude)
        self.assertIn("title", result.source_sections)
        self.assertIn("abstract", result.source_sections)
        self.assertIn("keywords", result.source_sections)
        self.assertIn("full_text_excerpt", result.source_sections)
        self.assertIn("AI governance", result.matched_keywords)
        self.assertGreaterEqual(result.keyword_overlap_score, 0.1)
        self.assertIn("cosine similarity 0.82", result.explanation)

    def test_local_topic_matcher_can_auto_filter_low_relevance(self) -> None:
        config = self._config(topic_prefilter_enabled=True, topic_prefilter_filter_low_relevance=True)

        with patch("analysis.topic_prefilter.load_embedding_runtime", return_value=(_FakeTorch, _FakeTokenizerLoader, _FakeModelLoader)), \
                patch.object(LocalTopicMatcher, "_embed_texts", return_value=[_FakeVector(1.0), _FakeVector(0.20)]):
            matcher = LocalTopicMatcher(config)
            result = matcher.score_paper(self._paper(title="Clinical biomarkers for oncology", abstract="Purely medical biomarker study."))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.classification, "LOW_RELEVANCE")
        self.assertTrue(result.should_exclude)
        self.assertIn("Automatic filtering is enabled", result.explanation)

    def test_local_topic_matcher_fails_gracefully_when_runtime_is_missing(self) -> None:
        config = self._config(topic_prefilter_enabled=True)

        with patch("analysis.topic_prefilter.load_embedding_runtime", side_effect=RuntimeError("missing runtime")):
            matcher = LocalTopicMatcher(config)

        self.assertFalse(matcher.enabled)
        self.assertIsNone(matcher.score_paper(self._paper()))

    def test_ai_screener_uses_topic_prefilter_to_exclude_low_relevance_papers(self) -> None:
        config = self._config(topic_prefilter_enabled=True, topic_prefilter_filter_low_relevance=True, llm_provider="heuristic")
        paper = self._paper(title="Medical imaging biomarkers", abstract="A medical imaging paper without AI governance content.")

        with patch("analysis.topic_prefilter.load_embedding_runtime", return_value=(_FakeTorch, _FakeTokenizerLoader, _FakeModelLoader)), \
                patch.object(LocalTopicMatcher, "_embed_texts", return_value=[_FakeVector(1.0), _FakeVector(0.18)]):
            screener = AIScreener(config)
            result = screener.screen(paper)

        self.assertEqual(result.decision, "exclude")
        self.assertEqual(result.topic_prefilter_label, "LOW_RELEVANCE")
        self.assertIn("local topic prefilter", result.exclusion_reason.lower())
        self.assertIn("topic prefilter", result.explanation.lower())
