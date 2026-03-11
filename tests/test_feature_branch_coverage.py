"""Targeted branch tests for the new semantic topic filtering and discovery controls."""

from __future__ import annotations

from collections import deque
from contextlib import nullcontext
import tempfile
import unittest
from pathlib import Path
import numpy as np
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from analysis.ai_screener import AIScreener
from analysis.relevance_scoring import RelevanceScorer
from analysis.topic_prefilter import LocalTopicMatcher, TopicMatchResult
from config import ResearchConfig
from discovery.core_client import COREClient
from discovery.europe_pmc_client import EuropePMCClient
from discovery.google_scholar_client import GoogleScholarClient
from models.paper import PaperMetadata, ScreeningResult
from reporting.report_generator import ReportGenerator
from utils import http


class _PrefilterTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class nn:
        class functional:
            @staticmethod
            def normalize(value, p=2, dim=1):  # noqa: ANN001, ARG004
                return {"normalized": value, "p": p, "dim": dim}

    @staticmethod
    def device(name: str) -> str:
        return name

    @staticmethod
    def no_grad():
        return nullcontext()


class _FakeTensor:
    def to(self, _device):  # noqa: ANN001
        return self

    def unsqueeze(self, _value: int):
        return self

    def expand(self, _size):  # noqa: ANN001
        return self

    def float(self):
        return self

    def size(self):
        return (2, 3, 4)

    def sum(self, dim=None):  # noqa: ANN001, ARG002
        return self

    def clamp(self, min=0.0):  # noqa: A002, ARG002
        return self

    def __mul__(self, other):  # noqa: ANN001
        return self

    def __truediv__(self, other):  # noqa: ANN001
        return self


class _PrefilterTokenizer:
    def __call__(self, texts, **kwargs):  # noqa: ANN001, ARG002
        _ = texts
        return {"attention_mask": _FakeTensor(), "input_ids": _FakeTensor()}


class _PrefilterModelOutput:
    last_hidden_state = _FakeTensor()


class _PrefilterModel:
    def to(self, _device):  # noqa: ANN001
        return self

    def eval(self):
        return self

    def __call__(self, **kwargs):  # noqa: ANN003, ARG002
        return _PrefilterModelOutput()


class _PrefilterTokenizerLoader:
    @staticmethod
    def from_pretrained(*args, **kwargs):  # noqa: ANN002, ANN003
        return _PrefilterTokenizer()


class _PrefilterModelLoader:
    @staticmethod
    def from_pretrained(*args, **kwargs):  # noqa: ANN002, ANN003
        return _PrefilterModel()


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


class _FakeLLMClient:
    enabled = True
    provider_name = "fake_llm"

    def __init__(self, responses: list[str | None]) -> None:
        self.responses = list(responses)

    def chat(self, *, system_prompt: str, user_prompt: str):  # noqa: ANN001
        _ = (system_prompt, user_prompt)
        return SimpleNamespace(content=self.responses.pop(0))


class _FakeScreener:
    def summarize_review(self, papers):  # noqa: ANN001
        _ = papers
        return None


class FeatureBranchCoverageTests(unittest.TestCase):
    """Exercise remaining uncovered branches in new feature modules."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.config = ResearchConfig(
            research_topic="AI governance in healthcare",
            research_question="How relevant are papers to AI governance and deployment in health systems?",
            review_objective="Keep papers about AI governance, evaluation, and deployment.",
            search_keywords=["AI governance", "healthcare AI", "deployment"],
            inclusion_criteria=["governance", "evaluation"],
            exclusion_criteria=["biomarker"],
            banned_topics=["crop irrigation"],
            include_pubmed=False,
            topic_prefilter_enabled=True,
            topic_prefilter_filter_low_relevance=True,
            data_dir=root / "data",
            papers_dir=root / "papers",
            results_dir=root / "results",
            database_path=root / "data" / "review.db",
            request_timeout_seconds=5,
        ).finalize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _paper(self, **overrides: object) -> PaperMetadata:
        payload = {
            "query_key": self.config.query_key,
            "title": "AI governance for hospital decision support",
            "authors": ["Ada Lovelace"],
            "abstract": "This paper evaluates governance and deployment choices for healthcare AI.",
            "year": 2024,
            "venue": "Journal of AI Policy",
            "doi": "10.1000/test",
            "source": "fixture",
            "raw_payload": {"keywords": ["AI governance", "deployment"]},
        }
        payload.update(overrides)
        return PaperMetadata(**payload)

    def _matcher(self, **config_overrides: object) -> LocalTopicMatcher:
        config = self.config.model_copy(update=config_overrides)
        with patch(
            "analysis.topic_prefilter.load_embedding_runtime",
            return_value=(_PrefilterTorch, _PrefilterTokenizerLoader, _PrefilterModelLoader),
        ):
            return LocalTopicMatcher(config)

    def test_topic_prefilter_helper_branches_cover_text_and_device_paths(self) -> None:
        matcher = self._matcher(topic_prefilter_text_mode="title_only")
        empty_text_paper = self._paper(raw_payload={})

        with patch.object(matcher, "_build_paper_text", return_value=("", [])):
            self.assertIsNone(matcher.score_paper(empty_text_paper))

        with patch.object(matcher, "_embed_texts", side_effect=RuntimeError("embedding failed")):
            self.assertIsNone(matcher.score_paper(self._paper()))

        string_keywords = matcher._paper_keywords(self._paper(raw_payload={"keyword": "AI governance | deployment, oversight"}))
        list_keywords = matcher._paper_keywords(self._paper(raw_payload={"subject_terms": ["AI", " ", "policy"]}))
        no_keywords = matcher._paper_keywords(self._paper(raw_payload={"keyword": "", "index_terms": []}))
        paper_text, sections = matcher._build_paper_text(
            self._paper(
                abstract="Ignored in title-only mode.",
                raw_payload={"keyword": "AI governance", "full_text_excerpt": "Long full text."},
            )
        )
        embedded = matcher._embed_texts(["review brief", "paper text"])

        self.assertEqual(string_keywords, ["AI governance", "deployment", "oversight"])
        self.assertEqual(list_keywords, ["AI", "policy"])
        self.assertEqual(no_keywords, [])
        self.assertIn("title", sections)
        self.assertNotIn("abstract", sections)
        self.assertEqual(matcher._classify_similarity(0.60), "REVIEW")
        self.assertEqual(matcher._resolve_device(_PrefilterTorch, "cuda"), "cpu")
        self.assertEqual(matcher._resolve_device(_PrefilterTorch, "cpu"), "cpu")
        self.assertEqual(embedded["p"], 2)
        self.assertIn("AI governance", paper_text)

    def test_ai_screener_branch_logging_and_topic_match_enrichment(self) -> None:
        config = self.config.model_copy(update={"llm_provider": "heuristic", "verbosity": "verbose", "log_screening_decisions": True, "topic_prefilter_enabled": False})
        topic_match = TopicMatchResult(
            similarity=0.66,
            score=66.0,
            threshold=55.0,
            review_threshold=0.55,
            high_threshold=0.75,
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            enabled=True,
            classification="REVIEW",
            should_exclude=False,
            keyword_overlap_score=0.5,
            matched_keywords=["AI governance"],
            source_sections=["title", "abstract"],
            explanation="Moderate semantic match.",
        )
        result = ScreeningResult(
            stage_one_decision="include",
            relevance_score=88.0,
            explanation="Strong match.",
            decision="include",
        )
        fake_client = _FakeLLMClient(["{\"decision\":\"include\"}", "{\"decision\":\"include\", \"relevance_score\": 88}", "debug response"])

        with patch("analysis.ai_screener.build_llm_client", return_value=fake_client):
            screener = AIScreener(config)
            with patch.object(screener.scorer, "evaluate_topic_match", return_value=topic_match), \
                 patch.object(screener.scorer, "quick_screen", return_value="maybe"), \
                 patch.object(screener.scorer, "deep_score", return_value=result):
                with self.assertLogs("analysis.ai_screener", level="INFO") as info_logs:
                    screened = screener.screen(self._paper())

            self.assertEqual(screened.topic_prefilter_label, "REVIEW")
            self.assertIn("Moderate semantic match", screened.explanation)
            self.assertTrue(any("Local topic prefilter" in message for message in info_logs.output))

            same_result = screener._enrich_with_topic_match(result, None)
            enriched = screener._enrich_with_topic_match(result, topic_match)
            self.assertIs(same_result, result)
            self.assertEqual(enriched.topic_prefilter_label, "REVIEW")
            self.assertIn("Moderate semantic match", enriched.explanation)

            screener.config.log_llm_prompts = True
            screener.config.log_llm_responses = True
            screener.config.verbosity = "ultra_verbose"
            with self.assertLogs("analysis.ai_screener", level="DEBUG") as debug_logs:
                content = screener._chat_completion(system_prompt="system prompt", user_prompt="user prompt")
            self.assertIsNotNone(content)
            self.assertTrue(any("LLM system prompt" in message for message in debug_logs.output))

        with patch("analysis.ai_screener.build_llm_client", return_value=_FakeLLMClient(["not json", '{"decision":"invalid","relevance_score":90}', '{"decision":"include"}'])):
            screener = AIScreener(self.config.model_copy(update={"llm_provider": "openai_compatible", "topic_prefilter_enabled": False}))
            with self.assertLogs("analysis.ai_screener", level="WARNING") as warning_logs:
                self.assertIsNone(screener._llm_stage_two(self._paper(), "include"))
                self.assertIsNone(screener._llm_stage_two(self._paper(), "include"))
                self.assertIsNone(screener._llm_stage_two(self._paper(), "include"))
                self.assertEqual(screener._parse_json_response("{broken json}"), {})
            combined = "\n".join(warning_logs.output)
            self.assertIn("no valid JSON", combined)
            self.assertIn("invalid decision", combined)
            self.assertIn("no relevance score", combined)
            self.assertIn("Failed to decode JSON response", combined)

    def test_google_scholar_helper_branches_cover_page_limit_and_fallback_parsing(self) -> None:
        config = self.config.model_copy(
            update={
                "google_scholar_enabled": True,
                "google_scholar_pages": 1,
                "google_scholar_results_per_page": 1,
                "results_per_page": 1,
                "pages_to_retrieve": 1,
                "discovery_strategy": "balanced",
                "verbosity": "ultra_verbose",
            }
        )
        client = GoogleScholarClient(config)
        page_html = '''
        <div class="gs_r gs_or gs_scl">
            <h3 class="gs_rt"><a href="https://example.org/paper-a">AI Governance in Hospitals</a></h3>
            <div class="gs_a">Ada Lovelace - Journal of AI Policy - 2024</div>
            <div class="gs_rs">A study of AI governance and deployment. DOI 10.1000/xyz123</div>
        </div>
        '''

        with patch("discovery.google_scholar_client.request_text", return_value=page_html) as request_mock:
            papers = client.search()
        self.assertEqual(len(papers), 1)
        self.assertEqual(request_mock.call_count, 1)

        noisy_page = '''
        <div class="gs_r gs_or gs_scl"><div>No title card</div></div>
        <div class="gs_r gs_or gs_scl">
            <h3 class="gs_rt"><a href="https://example.org/paper-b">&lt;b&gt;Policy&lt;/b&gt; and AI</a></h3>
            <div class="gs_a">Author One, Author Two - Venue - 2025</div>
            <div class="gs_rs">Snippet <b>text</b>.</div>
        </div>
        '''
        with self.assertLogs("discovery.google_scholar_client", level="DEBUG") as debug_logs:
            parsed = client._parse_page(noisy_page)
        self.assertEqual(len(parsed), 1)
        self.assertTrue(any("parsed result" in message for message in debug_logs.output))
        self.assertIsNone(client._parse_result_block('<div class="gs_r gs_or"><div>Missing title</div></div>'))
        self.assertEqual(client._extract_title_and_url("<div>no title</div>"), ("", None))
        self.assertEqual(client._extract_block_text(client.SNIPPET_PATTERN if hasattr(client, "SNIPPET_PATTERN") else __import__("re").compile("x"), "<div></div>"), "")
        self.assertIsNone(client._extract_url(__import__("re").compile("missing"), "<div></div>"))
        self.assertEqual(client._extract_doi("no doi here"), "")
        self.assertEqual(client._parse_meta(""), ([], "", None))
        self.assertEqual(client._clean_html_text("<b>Hello</b> &amp; world"), "Hello & world")

    def test_http_rate_limiting_and_backoff_cover_remaining_paths(self) -> None:
        limiter = http.RateLimiter(calls_per_second=0.0, max_requests_per_minute=1, request_delay_seconds=2.0)
        limiter._last_call = 0.0
        limiter._request_history = deque([0.0])

        with patch("utils.http.time.monotonic", side_effect=[1.0, 61.0]), patch("utils.http.time.sleep") as sleep_mock:
            limiter.wait()
        sleep_mock.assert_called_once_with(59.0)
        self.assertEqual(len(limiter._request_history), 1)

        limiter._request_history = deque([0.0, 30.0])
        limiter._prune_history(89.0)
        self.assertEqual(list(limiter._request_history), [30.0])

        response = Mock(spec=requests.Response)
        response.headers = {}
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=60,
            retry_max_attempts=4,
            retry_base_delay_seconds=2.0,
            retry_max_delay_seconds=30.0,
        )
        self.assertEqual(http._calculate_backoff_delay(response, 3, strategy="fixed"), 2.0)
        self.assertEqual(http._calculate_backoff_delay(response, 3, strategy="linear"), 6.0)

        cache = http.PersistentResponseCache(Path(self.temp_dir.name), ttl_seconds=60)
        key = http._build_cache_key("GET", "https://example.org/api", {"params": {"q": "llm"}})
        cache.store(key, kind="json", payload={"ok": True})
        http.configure_http_logging(enabled=True, log_payloads=True)
        with self.assertLogs("utils.http", level="INFO") as logs:
            payload = http._load_cached_payload(
                "GET",
                "https://example.org/api",
                expected_kind="json",
                use_cache=True,
                kwargs={"params": {"q": "llm"}},
            )
        self.assertEqual(payload, {"ok": True})
        self.assertTrue(any("HTTP cache hit" in message for message in logs.output))

    def test_relevance_scoring_and_reporting_cover_remaining_decision_paths(self) -> None:
        scorer = RelevanceScorer(self.config.model_copy(update={"decision_mode": "triage"}), topic_matcher=None)
        include_paper = self._paper(
            title="AI governance evaluation for healthcare deployment",
            abstract="AI governance and evaluation drive healthcare AI deployment oversight.",
        )
        maybe_paper = self._paper(title="Evaluation of oversight workflows", abstract="Governance evaluation with limited detail.")
        exclude_paper = self._paper(title="Clinical biomarkers", abstract="Biomarker study without governance signals.")
        topic_block = TopicMatchResult(
            similarity=0.20,
            score=20.0,
            threshold=55.0,
            review_threshold=0.55,
            high_threshold=0.75,
            model_name="mini",
            enabled=True,
            classification="LOW_RELEVANCE",
            should_exclude=True,
            keyword_overlap_score=0.0,
            matched_keywords=[],
            source_sections=["title"],
            explanation="Low relevance.",
        )

        self.assertEqual(scorer.quick_screen(include_paper), "include")
        self.assertEqual(scorer.quick_screen(maybe_paper), "maybe")
        self.assertEqual(scorer.quick_screen(exclude_paper), "exclude")
        self.assertEqual(scorer.quick_screen(include_paper, topic_match=topic_block), "exclude")
        self.assertIsNone(scorer.evaluate_topic_match(include_paper))
        self.assertEqual(scorer._classify_domain("unrelated topic"), "general")
        self.assertEqual(scorer._decision_from_score(71.0, "maybe"), "include")
        self.assertEqual(scorer._decision_from_score(65.0, "maybe"), "maybe")
        strict_scorer = RelevanceScorer(self.config.model_copy(update={"decision_mode": "strict"}))
        self.assertEqual(strict_scorer._decision_from_score(60.0, "include"), "exclude")

        review_topic_match = TopicMatchResult(
            similarity=0.60,
            score=60.0,
            threshold=55.0,
            review_threshold=0.55,
            high_threshold=0.75,
            model_name="mini",
            enabled=True,
            classification="REVIEW",
            should_exclude=False,
            keyword_overlap_score=0.4,
            matched_keywords=["AI governance"],
            source_sections=["title", "abstract"],
            explanation="Review-level relevance.",
        )
        result = scorer.deep_score(include_paper, stage_one_decision="include", topic_match=review_topic_match)
        self.assertIn("semantic_topic_match", result.evaluation_breakdown)
        self.assertIn(result.decision, {"include", "maybe", "exclude"})

        generator_config = self.config.model_copy(update={"incremental_report_regeneration": True, "run_mode": "collect"})
        generator = ReportGenerator(generator_config, _FakeScreener())
        ranked = [self._paper(relevance_score=92.0, inclusion_decision="include")]
        summary = generator._heuristic_summary(ranked, ranked)
        self.assertIn("AI screening was not executed", summary)

        db_path = Path(generator_config.results_dir) / "included_papers.db"
        first = generator._write_decision_database("included_papers.db", "included", ranked)
        second = generator._write_decision_database("included_papers.db", "included", ranked)
        self.assertEqual(first, second)
        self.assertEqual(first, db_path)

        fingerprint_path = generator._artifact_fingerprint_path(db_path)
        fingerprint_path.write_text("fingerprint", encoding="utf-8")
        with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
            self.assertIsNone(generator._read_artifact_fingerprint(db_path))

    def test_europe_pmc_and_core_edge_branches_cover_fallback_metadata(self) -> None:
        europe_client = EuropePMCClient(self.config.model_copy(update={"europe_pmc_enabled": True}))
        europe_item = {
            "id": "EPMC2",
            "title": "Europe fallback",
            "authorString": "Ada Lovelace, Grace Hopper",
            "journalInfo": {},
            "pubYear": "2025",
            "fullTextUrlList": {"fullTextUrl": {"url": "https://example.org/europe.pdf"}},
        }
        parsed_europe = europe_client._parse_item(europe_item)
        self.assertEqual(parsed_europe.authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(parsed_europe.venue, "")
        self.assertEqual(parsed_europe.pdf_link, "https://example.org/europe.pdf")

        core_config = self.config.model_copy(
            update={
                "core_enabled": True,
                "api_settings": self.config.api_settings.model_copy(update={"core_api_key": "core-key"}),
                "pages_to_retrieve": 1,
                "results_per_page": 5,
                "discovery_strategy": "precise",
            }
        )
        core_client = COREClient(core_config)
        self.assertEqual(core_client.session.headers["Authorization"], "Bearer core-key")
        payload = {
            "results": [
                {"title": "Out of range", "yearPublished": 2010},
                {"yearPublished": 2024},
                {
                    "id": 1,
                    "title": "CORE valid",
                    "authors": [],
                    "abstract": "Abstract",
                    "yearPublished": 2024,
                    "publisher": "CORE Venue",
                    "identifiers": [{"type": "repo", "identifier": "abc"}],
                    "sourceFulltextUrls": ["https://example.org/core.pdf"],
                },
            ]
        }
        with patch("discovery.core_client.request_json", return_value=payload):
            results = core_client.search()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].pdf_link, "https://example.org/core.pdf")
        self.assertEqual(results[0].external_ids["repo"], "abc")



    def test_relevance_scoring_covers_hard_exclusion_and_exclusion_reason_branch(self) -> None:
        scorer = RelevanceScorer(self.config.model_copy(update={"decision_mode": "triage"}), topic_matcher=None)
        banned_paper = self._paper(title="Crop irrigation planning", abstract="Crop irrigation and water management.")
        excluded_paper = self._paper(title="Governance biomarkers", abstract="Biomarker criteria dominate this paper.")

        self.assertEqual(scorer.quick_screen(banned_paper), "exclude")
        excluded = scorer.deep_score(excluded_paper, stage_one_decision="exclude")
        self.assertIn("exclusion criteria matched", excluded.exclusion_reason)

    def test_europe_pmc_search_breaks_on_empty_payload_and_handles_dict_author_list(self) -> None:
        config = self.config.model_copy(update={"europe_pmc_enabled": True, "discovery_strategy": "precise", "pages_to_retrieve": 1})
        client = EuropePMCClient(config)
        with patch("discovery.europe_pmc_client.request_json", return_value=None):
            self.assertEqual(client.search(), [])

        parsed = client._parse_item(
            {
                "id": "EPMC3",
                "title": "Dict authors",
                "authorList": {"author": {"fullName": "Ada Lovelace"}},
                "journalInfo": {"journal": {"title": "Venue"}},
            }
        )
        self.assertEqual(parsed.authors, ["Ada Lovelace"])

    def test_report_generator_and_google_scholar_cover_remaining_small_fallbacks(self) -> None:
        config = self.config.model_copy(update={"incremental_report_regeneration": True, "google_scholar_enabled": True})
        generator = ReportGenerator(config, _FakeScreener())
        artifact_path = Path(config.results_dir) / "notes.txt"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("old", encoding="utf-8")

        with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
            generator._write_text_artifact(artifact_path, "new")
        self.assertEqual(artifact_path.read_text(encoding="utf-8"), "new")
        self.assertIsNone(generator._read_artifact_fingerprint(Path(config.results_dir) / "missing.db"))

        scholar = GoogleScholarClient(config.model_copy(update={"verbosity": "ultra_verbose"}))
        skipped = scholar._parse_page('<div class="gs_r gs_or"><h3 class="gs_rt"></h3></div>')
        self.assertEqual(skipped, [])

    def test_launcher_and_benchmark_helpers_cover_remaining_edge_paths(self) -> None:
        from benchmark_report import _build_case, build_report_artifacts, main as benchmark_main
        from ui.launcher import has_explicit_run_arguments

        self.assertFalse(has_explicit_run_arguments(SimpleNamespace(ui=False, wizard=False, analysis_passes=[]), argv=None))
        markdown, text, payload = build_report_artifacts([])
        self.assertIn("No benchmarks executed", text)
        self.assertEqual(payload["summary"]["benchmarks_executed"], 0)
        with self.assertRaises(KeyError):
            _build_case({}, "missing", lambda _root: 0)
        with patch("benchmark_report.run_benchmark_report", return_value=0):
            with self.assertRaises(SystemExit) as exc:
                benchmark_main()
        self.assertEqual(exc.exception.code, 0)

    def test_small_client_and_helper_fallbacks_cover_remaining_lines(self) -> None:
        from acquisition.full_text_extractor import FullTextExtractor
        from discovery.crossref_client import CrossrefClient
        from discovery.fixture_client import FixtureDiscoveryClient
        from discovery.manual_import_client import ManualImportClient
        from utils.deduplication import deduplicate_papers

        pdf_path = Path(self.temp_dir.name) / "tiny.pdf"
        pdf_path.write_bytes(b"%PDF-1.7")
        fake_page = SimpleNamespace(extract_text=lambda: "ABCDE")
        fake_module = SimpleNamespace(PdfReader=lambda _path: SimpleNamespace(pages=[fake_page]))
        with patch.dict("sys.modules", {"pypdf": fake_module}):
            self.assertIsNone(FullTextExtractor(max_chars=0).extract_excerpt(pdf_path))

        crossref = CrossrefClient(self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1}))
        with patch("discovery.crossref_client.request_json", return_value=None):
            self.assertEqual(crossref.search(), [])

        fixture_path = Path(self.temp_dir.name) / "fixture.json"
        fixture_path.write_text('[{"title": "Paper A", "source": "fixture"}]', encoding="utf-8")
        fixture_client = FixtureDiscoveryClient(self.config.model_copy(update={"fixture_data_path": fixture_path}))
        self.assertEqual(fixture_client.fetch_citations(self._paper(title="Unknown", doi="10.1000/unknown")), [])

        manual_path = Path(self.temp_dir.name) / "manual.csv"
        manual_path.write_text("title\nPaper A\n", encoding="utf-8")
        manual_client = ManualImportClient(self.config, path=manual_path)
        self.assertFalse(manual_client._to_bool(None))

        papers = [self._paper(title="Alpha", doi=None), self._paper(title="Beta", doi=None)]
        with patch("utils.deduplication.cosine_similarity", return_value=np.array([[1.0, 0.5], [0.5, 1.0]])), \
             patch("utils.deduplication.TfidfVectorizer.fit_transform", return_value=object()):
            deduped = deduplicate_papers(papers, title_similarity_threshold=0.9)
        self.assertEqual(len(deduped), 2)

    def test_config_brief_and_cli_verbosity_branches_cover_new_fields(self) -> None:
        from config import build_arg_parser, parse_analysis_pass

        scholar_config = self.config.model_copy(update={"google_scholar_enabled": True, "topic_prefilter_enabled": True})
        self.assertIn("Google Scholar pages", scholar_config.screening_brief)
        self.assertIn("Local topic prefilter", scholar_config.screening_brief)

        parser = build_arg_parser()
        with patch("builtins.input", return_value=""):
            verbose_config = ResearchConfig.from_cli(parser.parse_args(["--topic", "Topic", "--keywords", "llm", "--verbose"]))
        with patch("builtins.input", return_value=""):
            debug_config = ResearchConfig.from_cli(parser.parse_args(["--topic", "Topic", "--keywords", "llm", "--ultra-verbose"]))
        self.assertEqual(verbose_config.verbosity, "verbose")
        self.assertEqual(debug_config.verbosity, "ultra_verbose")

        with self.assertRaises(ValueError):
            parse_analysis_pass("[1,2,3]")


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()











