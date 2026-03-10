"""Additional branch-heavy tests that raise coverage across config, clients, and helpers."""

from __future__ import annotations

import json
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from acquisition.full_text_extractor import FullTextExtractor
from acquisition.pdf_fetcher import PDFFetcher
from analysis.ai_screener import AIScreener
import coverage_report
from config import ResearchConfig, build_arg_parser, parse_analysis_pass
from database import DatabaseManager
from discovery.arxiv_client import ArxivClient
from discovery.crossref_client import CrossrefClient
from discovery.fixture_client import FixtureDiscoveryClient
from discovery.openalex_client import OpenAlexClient
from discovery.pubmed_client import PubMedClient
from discovery.semantic_scholar_client import SemanticScholarClient
from models.paper import PaperMetadata, ScreeningResult
from reporting.report_generator import ReportGenerator
from utils.text_processing import extract_salient_sentence, reconstruct_inverted_abstract, safe_year


def _make_paper(title: str = "Paper Title", **overrides: object) -> PaperMetadata:
    """Create a small valid paper model for helper-oriented tests."""

    payload = {
        "query_key": "query-key",
        "title": title,
        "authors": ["Ada Lovelace"],
        "abstract": "Large language models help with screening and evaluation.",
        "year": 2024,
        "venue": "Test Venue",
        "doi": "10.1000/test",
        "source": "test",
    }
    payload.update(overrides)
    return PaperMetadata(**payload)


class MiscHighCoverageTests(unittest.TestCase):
    """Cover smaller untested branches across the non-UI codebase."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.root = root
        self.config = ResearchConfig(
            research_topic="Systematic review automation",
            search_keywords=["llm", "screening"],
            data_dir=root / "data",
            papers_dir=root / "papers",
            results_dir=root / "results",
            database_path=root / "data" / "review.db",
            request_timeout_seconds=5,
        ).finalize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_config_validation_edges_and_interactive_reprompts(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique pass names"):
            ResearchConfig(
                research_topic="Topic",
                search_keywords=["llm"],
                analysis_passes=[
                    {"name": "dup", "llm_provider": "heuristic", "threshold": 60},
                    {"name": "dup", "llm_provider": "heuristic", "threshold": 70},
                ],
            )
        with self.assertRaisesRegex(ValueError, "greater than or equal"):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], year_range_start=2026, year_range_end=2025)
        with self.assertRaisesRegex(ValueError, "at least 1"):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], pages_to_retrieve=0)
        with self.assertRaisesRegex(ValueError, "at least 1"):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], max_discovered_records=0)
        with self.assertRaisesRegex(ValueError, "at least 0"):
            ResearchConfig(research_topic="Topic", search_keywords=["llm"], min_discovered_records=-1)

        detailed = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            max_discovered_records=5,
            min_discovered_records=2,
        ).finalize()
        self.assertIn("Maximum discovered records: 5", detailed.screening_brief)
        self.assertIn("Minimum discovered records: 2", detailed.screening_brief)

        self.assertEqual(parse_analysis_pass("json-pass:heuristic:50").name, "json-pass")
        self.assertEqual(ResearchConfig(research_topic="Topic", search_keywords=["llm"], analysis_passes="one:heuristic:50").analysis_passes[0].name, "one")
        self.assertEqual(ResearchConfig(research_topic="Topic", search_keywords=["llm"], analysis_passes=1).analysis_passes, [])
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            parse_analysis_pass("   ")
        with self.assertRaisesRegex(ValueError, "Extended analysis pass format"):
            parse_analysis_pass("a|b|c")
        with self.assertRaisesRegex(ValueError, "must use name:provider:threshold"):
            parse_analysis_pass("broken")

        parser = build_arg_parser()
        args = parser.parse_args([])
        answers = iter(
            [
                "Coverage topic",
                "Question",
                "Objective",
                "llm, review",
                "",
                "",
                "",
                "correction;editorial",
                "AND",
                "oops",
                "2",
                "2019",
                "2026",
                "ten",
                "12",
                "maybe",
                "yes",
                "bad",
                "70",
                "y",
                "n",
                "what",
                "yes",
            ]
        )
        with patch("builtins.input", side_effect=lambda _prompt: next(answers)), patch("builtins.print") as print_mock:
            config = ResearchConfig.from_cli(args)
        printed = " ".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("Please enter a valid integer.", printed)
        self.assertIn("Please enter a valid number.", printed)
        self.assertIn("Please answer yes or no.", printed)
        self.assertTrue(config.include_pubmed)

    def test_small_model_and_text_helpers_cover_remaining_edges(self) -> None:
        with self.assertRaisesRegex(ValueError, "Paper title cannot be empty"):
            PaperMetadata(title="   ")
        self.assertEqual(PaperMetadata(title="A", authors="Ada; Bob ; ").authors, ["Ada", "Bob"])

        self.assertEqual(reconstruct_inverted_abstract(None), "")
        with patch("utils.text_processing.re.split", return_value=[]):
            self.assertEqual(extract_salient_sentence("No sentences", ["llm"]), "")
        self.assertIsNone(safe_year(""))
        self.assertIsNone(safe_year("bad"))

    def test_full_text_extractor_covers_blank_pages_and_truncation(self) -> None:
        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        fake_module = types.SimpleNamespace(
            PdfReader=lambda _path: SimpleNamespace(
                pages=[
                    FakePage("   "),
                    FakePage("ABCDE"),
                    FakePage("FGHIJ"),
                ]
            )
        )
        extractor = FullTextExtractor(max_chars=5)
        pdf_path = self.root / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.7")

        with patch.dict("sys.modules", {"pypdf": fake_module}):
            self.assertEqual(extractor.extract_excerpt(pdf_path), "ABCDE")

        fake_empty_module = types.SimpleNamespace(
            PdfReader=lambda _path: SimpleNamespace(pages=[FakePage(" "), FakePage("")])
        )
        with patch.dict("sys.modules", {"pypdf": fake_empty_module}):
            self.assertIsNone(extractor.extract_excerpt(pdf_path))

    def test_pdf_fetcher_and_reporting_cover_remaining_output_branches(self) -> None:
        fetcher = PDFFetcher(self.config)
        paper = _make_paper(title="PDF test", doi="10.1000/pdf")

        with patch("acquisition.pdf_fetcher.request_content", return_value=None):
            self.assertIsNone(fetcher.download_pdf(paper, "https://example.org/file.pdf"))

        response = Mock()
        response.headers = {"Content-Type": "text/plain"}
        response.iter_content = Mock(side_effect=[iter([b"%PDF"]), iter([b" body"])])
        with patch("acquisition.pdf_fetcher.request_content", return_value=response):
            pdf_path = fetcher.download_pdf(paper, "https://example.org/file.pdf")
        self.assertIsNotNone(pdf_path)
        self.assertEqual(Path(pdf_path).read_bytes(), b"%PDF body")

        ai_screener = Mock(spec=AIScreener)
        ai_screener.summarize_review.return_value = "LLM generated summary."
        generator = ReportGenerator(self.config, ai_screener)
        ranked = [_make_paper(relevance_score=90.0, inclusion_decision="include")]
        summary_path = generator._write_review_summary(ranked, ranked, None)
        self.assertIn("LLM generated summary.", summary_path.read_text(encoding="utf-8"))
        self.assertIn("pass_fast_score", generator._paper_to_dict_keys(["fast"]))

    def test_database_and_coverage_report_main_cover_remaining_helper_branches(self) -> None:
        manager = DatabaseManager(self.config.database_path)
        manager.initialize()
        paper = _make_paper()
        stored = manager.upsert_papers([paper], self.config.query_key)
        result = ScreeningResult(relevance_score=91.0, decision="include", stage_one_decision="include")

        analysis_all = manager.get_papers_for_analysis(self.config.query_key, limit=5, resume_mode=False)
        self.assertEqual(len(analysis_all), 1)

        manager.cache_screening_result(
            paper=stored[0],
            paper_cache_key="paper-key",
            screening_context_key="ctx",
            result=result,
        )
        manager.cache_screening_result(
            paper=stored[0],
            paper_cache_key="paper-key",
            screening_context_key="ctx",
            result=ScreeningResult(relevance_score=92.0, decision="maybe", stage_one_decision="maybe"),
        )
        cached = manager.get_cached_screening_result("paper-key", "ctx")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.decision, "maybe")
        self.assertIsNone(manager.get_cached_screening_result("missing", "ctx"))

        manager.update_screening_result(999999, result)
        manager.update_pdf_info(999999, pdf_link=None, pdf_path=None, open_access=False)
        manager.close()

        with patch("coverage_report.run_coverage_report", return_value=0):
            with self.assertRaises(SystemExit) as exc:
                coverage_report.main()
        self.assertEqual(exc.exception.code, 0)

    def test_discovery_clients_cover_remaining_edge_branches(self) -> None:
        crossref_config = self.config.model_copy(
            update={
                "results_per_page": 1,
                "pages_to_retrieve": 2,
                "api_settings": self.config.api_settings.model_copy(update={"crossref_mailto": "carina@example.com"}),
            }
        )
        crossref_client = CrossrefClient(crossref_config)
        payload = {"message": {"items": [{"title": ["T1"], "author": [{"given": "Ada", "family": "Lovelace"}]}]}}
        precise_crossref_config = crossref_config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1})
        crossref_client = CrossrefClient(precise_crossref_config)
        with patch("discovery.crossref_client.request_json", side_effect=lambda *args, **kwargs: payload) as request_mock:
            papers = crossref_client.search()
        self.assertEqual(len(papers), 1)
        self.assertEqual(request_mock.call_args_list[0].kwargs["params"]["mailto"], "carina@example.com")

        title_only_fixture = self.root / "fixture.json"
        title_only_fixture.write_text(json.dumps([_make_paper(doi=None).model_dump(mode="json")]), encoding="utf-8")
        fixture_config = self.config.model_copy(update={"fixture_data_path": title_only_fixture})
        fixture_client = FixtureDiscoveryClient(fixture_config)
        title_only = _make_paper(doi=None)
        self.assertEqual(fixture_client.fetch_references(_make_paper(title="missing", doi="10.1000/miss")), [])
        self.assertEqual(fixture_client.fetch_citations(title_only), [])
        with self.assertRaisesRegex(ValueError, "fixture_data_path must be provided"):
            FixtureDiscoveryClient(self.config.model_copy(update={"fixture_data_path": None}))

        openalex_config = crossref_config
        openalex_client = OpenAlexClient(openalex_config)
        search_payload = {"results": [{"display_name": "Known title", "authorships": [], "ids": {}, "referenced_works": []}]}
        with patch("discovery.openalex_client.request_json", side_effect=[search_payload]):
            resolved = openalex_client.resolve_work(_make_paper(title="Known title", doi=None))
        self.assertIsNotNone(resolved)
        with patch.object(openalex_client, "resolve_work", return_value=_make_paper(external_ids={"openalex": "W123"})), patch(
            "discovery.openalex_client.request_json",
            return_value=None,
        ):
            self.assertEqual(openalex_client.fetch_citations(_make_paper()), [])

        semantic_client = SemanticScholarClient(crossref_config)
        parsed = semantic_client._parse_paper({"title": "Semantic", "authors": [], "externalIds": {}, "openAccessPdf": {}})
        self.assertIsNone(parsed.doi)
        with patch("discovery.semantic_scholar_client.request_json", return_value=None):
            self.assertEqual(semantic_client.search(), [])

        arxiv_client = ArxivClient(crossref_config.model_copy(update={"boolean_operators": "weird"}))
        self.assertEqual(arxiv_client._build_search_query("llm benchmark"), 'all:"llm benchmark"')
        self.assertEqual(arxiv_client._parse_entry(ET.fromstring("<entry xmlns='http://www.w3.org/2005/Atom'></entry>")), None)
        with patch("discovery.arxiv_client.request_text", return_value=None):
            self.assertEqual(arxiv_client.search(), [])

        pubmed_client = PubMedClient(self.config.model_copy(update={"include_pubmed": True}))
        self.assertIsNone(pubmed_client._parse_article(ET.fromstring("<PubmedArticle />")))
        article_xml = ET.fromstring(
            """
            <PubmedArticle>
              <MedlineCitation>
                <PMID>123</PMID>
                <Article>
                  <ArticleTitle>Clinical review</ArticleTitle>
                  <Abstract><AbstractText>Useful abstract.</AbstractText></Abstract>
                  <AuthorList><Author><CollectiveName>Research Group</CollectiveName></Author></AuthorList>
                  <Journal><Title>Journal</Title><JournalIssue><PubDate><MedlineDate>2024 Jan</MedlineDate></PubDate></JournalIssue></Journal>
                </Article>
              </MedlineCitation>
              <PubmedData>
                <ArticleIdList>
                  <ArticleId IdType='pmc'>PMC123</ArticleId>
                </ArticleIdList>
              </PubmedData>
            </PubmedArticle>
            """
        )
        parsed_pubmed = pubmed_client._parse_article(article_xml)
        self.assertEqual(parsed_pubmed.authors, ["Research Group"])
        self.assertEqual(parsed_pubmed.year, 2024)
        self.assertTrue(parsed_pubmed.open_access)
        self.assertEqual(parsed_pubmed.external_ids["pmcid"], "PMC123")


if __name__ == "__main__":
    unittest.main()
