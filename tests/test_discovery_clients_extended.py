"""Extended tests for discovery client pagination, parsing, and helper branches."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import unittest
from unittest.mock import Mock, patch

from config import ResearchConfig
from discovery.arxiv_client import ArxivClient
from discovery.core_client import COREClient
from discovery.crossref_client import CrossrefClient
from discovery.europe_pmc_client import EuropePMCClient
from discovery.openalex_client import OpenAlexClient
from discovery.pubmed_client import PubMedClient
from discovery.semantic_scholar_client import SemanticScholarClient
from discovery.springer_client import SpringerClient
from models.paper import PaperMetadata


class DiscoveryClientsExtendedTests(unittest.TestCase):
    """Exercise source-specific search, parsing, and resolution helper methods."""

    def setUp(self) -> None:
        self.config = ResearchConfig(
            research_topic="Large language models",
            search_keywords=["survey", "benchmark"],
            pages_to_retrieve=2,
            results_per_page=2,
            openalex_enabled=True,
            semantic_scholar_enabled=True,
            crossref_enabled=True,
            include_pubmed=True,
            disable_progress_bars=True,
        ).finalize()

    def test_openalex_search_resolve_references_and_citations(self) -> None:
        config = self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1})
        client = OpenAlexClient(config)
        search_payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Paper A",
                    "authorships": [{"author": {"display_name": "Author One"}}],
                    "abstract_inverted_index": {"hello": [0], "world": [1]},
                    "publication_year": 2024,
                    "primary_location": {"source": {"display_name": "Venue A"}},
                    "ids": {"doi": "https://doi.org/10.1000/a"},
                    "cited_by_count": 3,
                    "referenced_works": ["WREF1"],
                    "open_access": {"is_oa": True, "oa_url": "https://example.org/a.pdf"},
                    "best_oa_location": {"pdf_url": "https://example.org/a.pdf"},
                }
            ]
        }
        citation_payload = {
            "results": [
                {
                    "id": "https://openalex.org/W2",
                    "display_name": "Citation Paper",
                    "authorships": [],
                    "abstract_inverted_index": {"citing": [0]},
                    "publication_year": 2025,
                    "primary_location": {"source": {"display_name": "Venue B"}},
                    "ids": {"doi": "https://doi.org/10.1000/b"},
                    "cited_by_count": 1,
                    "referenced_works": [],
                    "open_access": {"is_oa": False},
                }
            ]
        }
        reference_payload = {
            "id": "https://openalex.org/WREF1",
            "display_name": "Reference Paper",
            "authorships": [],
            "abstract_inverted_index": {"reference": [0]},
            "publication_year": 2023,
            "primary_location": {"source": {"display_name": "Venue Ref"}},
            "ids": {"doi": "https://doi.org/10.1000/ref"},
            "cited_by_count": 2,
            "referenced_works": [],
            "open_access": {"is_oa": False},
        }

        def fake_request_json(_session, _method, _url, **kwargs):
            params = kwargs.get("params") or {}
            if str(_url).endswith("/WREF1"):
                return reference_payload
            if str(_url).endswith("/W1"):
                return search_payload["results"][0]
            if str(params.get("filter", "")).startswith("cites:"):
                return citation_payload
            return search_payload

        with patch("discovery.openalex_client.request_json", side_effect=fake_request_json):
            papers = client.search()
            resolved = client.resolve_work(PaperMetadata(title="Paper A", doi="10.1000/a", source="test"))
            references = client.fetch_references(PaperMetadata(title="Paper A", doi="10.1000/a", source="test"))
            citations = client.fetch_citations(PaperMetadata(title="Paper A", doi="10.1000/a", source="test"))

        self.assertGreaterEqual(len(papers), 1)
        self.assertIsNotNone(resolved)
        self.assertEqual(references[0].title, "Reference Paper")
        self.assertEqual(citations[0].title, "Citation Paper")

    def test_openalex_handles_empty_payloads_and_external_id_resolution(self) -> None:
        config = self.config.model_copy(
            update={
                "discovery_strategy": "precise",
                "pages_to_retrieve": 1,
                "api_settings": self.config.api_settings.model_copy(update={"crossref_mailto": "carina@example.com"}),
            }
        )
        client = OpenAlexClient(config)
        resolved_payload = {
            "id": "https://openalex.org/W123",
            "display_name": "Resolved Paper",
            "authorships": [],
            "abstract_inverted_index": {"resolved": [0]},
            "publication_year": 2024,
            "primary_location": {"source": {"display_name": "Venue"}},
            "ids": {"doi": "https://doi.org/10.1000/resolved"},
            "cited_by_count": 0,
            "referenced_works": [],
            "open_access": {"is_oa": False},
        }

        with patch("discovery.openalex_client.request_json", side_effect=[None, resolved_payload, None]):
            search_results = client.search()
            resolved = client.resolve_work(
                PaperMetadata(
                    title="Resolved Paper",
                    source="test",
                    external_ids={"openalex": "https://openalex.org/W123"},
                )
            )
            no_citations = client.fetch_citations(PaperMetadata(title="Unresolved", source="test"))

        self.assertEqual(search_results, [])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.title, "Resolved Paper")
        self.assertEqual(no_citations, [])

    def test_openalex_fetch_work_by_id_and_references_handle_missing_records(self) -> None:
        client = OpenAlexClient(self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1}))

        with patch("discovery.openalex_client.request_json", side_effect=[{}, None]):
            missing_work = client.fetch_work_by_id("W404")
            missing_references = client.fetch_references(PaperMetadata(title="Missing", source="test"))

        self.assertIsNone(missing_work)
        self.assertEqual(missing_references, [])

    def test_crossref_and_semantic_scholar_search_parse_expected_fields(self) -> None:
        crossref_payload = {
            "message": {
                "items": [
                    {
                        "title": ["Crossref Paper"],
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "abstract": "<jats:p>Abstract</jats:p>",
                        "published-online": {"date-parts": [[2024, 6, 1]]},
                        "container-title": ["Crossref Venue"],
                        "DOI": "10.1000/crossref",
                        "is-referenced-by-count": 7,
                        "reference": [{"DOI": "10.1000/ref"}],
                        "link": [{"content-type": "application/pdf", "URL": "https://example.org/crossref.pdf"}],
                    }
                ]
            }
        }
        semantic_payload = {
            "data": [
                {
                    "paperId": "S1",
                    "title": "Semantic Paper",
                    "abstract": "Abstract",
                    "year": 2025,
                    "venue": "Semantic Venue",
                    "authors": [{"name": "Grace Hopper"}],
                    "citationCount": 4,
                    "referenceCount": 2,
                    "externalIds": {"DOI": "10.1000/semantic"},
                    "openAccessPdf": {"url": "https://example.org/semantic.pdf"},
                }
            ]
        }
        with patch("discovery.crossref_client.request_json", return_value=crossref_payload):
            crossref_results = CrossrefClient(self.config).search()
        with patch("discovery.semantic_scholar_client.request_json", return_value=semantic_payload):
            semantic_results = SemanticScholarClient(self.config).search()

        self.assertEqual(crossref_results[0].authors, ["Ada Lovelace"])
        self.assertEqual(crossref_results[0].pdf_link, "https://example.org/crossref.pdf")
        self.assertEqual(semantic_results[0].doi, "10.1000/semantic")
        self.assertTrue(semantic_results[0].open_access)

    def test_europe_pmc_and_core_search_parse_expected_fields(self) -> None:
        europe_pmc_payload = {
            "resultList": {
                "result": [
                    {
                        "id": "EPMC1",
                        "pmid": "123456",
                        "doi": "10.1000/europepmc",
                        "title": "Europe PMC Paper",
                        "authorList": {"author": [{"fullName": "Rosalind Franklin"}]},
                        "journalInfo": {"journal": {"title": "Europe PMC Venue"}},
                        "pubYear": "2024",
                        "abstractText": "Europe PMC abstract",
                        "citedByCount": 3,
                        "isOpenAccess": True,
                        "hasPDF": True,
                        "fullTextUrlList": {"fullTextUrl": [{"url": "https://example.org/europepmc.pdf"}]},
                    }
                ]
            }
        }
        core_payload = {
            "results": [
                {
                    "id": 99,
                    "title": "CORE Paper",
                    "authors": [{"name": "Katherine Johnson"}],
                    "abstract": "CORE abstract",
                    "yearPublished": 2024,
                    "publisher": "CORE Venue",
                    "doi": "10.1000/core",
                    "citationCount": 5,
                    "references": ["10.1000/core-ref"],
                    "downloadUrl": "https://example.org/core.pdf",
                    "identifiers": [{"type": "CORE_ID", "identifier": "99"}],
                }
            ]
        }

        with patch("discovery.europe_pmc_client.request_json", return_value=europe_pmc_payload):
            europe_pmc_results = EuropePMCClient(
                self.config.model_copy(update={"europe_pmc_enabled": True, "pages_to_retrieve": 1})
            ).search()
        with patch("discovery.core_client.request_json", return_value=core_payload):
            core_results = COREClient(self.config.model_copy(update={"core_enabled": True, "pages_to_retrieve": 1})).search()

        self.assertEqual(europe_pmc_results[0].authors, ["Rosalind Franklin"])
        self.assertEqual(europe_pmc_results[0].pdf_link, "https://example.org/europepmc.pdf")
        self.assertEqual(core_results[0].doi, "10.1000/core")
        self.assertTrue(core_results[0].open_access)

    def test_semantic_scholar_api_key_headers_and_per_source_limit_breaks(self) -> None:
        config = self.config.model_copy(
            update={
                "discovery_strategy": "precise",
                "pages_to_retrieve": 2,
                "results_per_page": 1,
                "api_settings": self.config.api_settings.model_copy(update={"semantic_scholar_api_key": "sem-key"}),
            }
        )
        payload = {
            "data": [
                {
                    "paperId": "S2",
                    "title": "Semantic Limited Paper",
                    "abstract": "Abstract",
                    "year": 2025,
                    "venue": "Semantic Venue",
                    "authors": [{"name": "Grace Hopper"}],
                    "citationCount": 4,
                    "referenceCount": 2,
                    "externalIds": {"DOI": "10.1000/semantic-limit"},
                    "openAccessPdf": {"url": "https://example.org/semantic-limit.pdf"},
                }
            ]
        }

        with patch("discovery.semantic_scholar_client.request_json", side_effect=[payload, payload]):
            client = SemanticScholarClient(config)
            results = client.search()

        self.assertEqual(client.session.headers["x-api-key"], "sem-key")
        self.assertEqual(len(results), config.per_source_limit)

    def test_clients_pick_up_configured_rate_limits(self) -> None:
        tuned = self.config.model_copy(
            update={
                "api_settings": self.config.api_settings.model_copy(
                    update={
                        "openalex_calls_per_second": 4.5,
                        "semantic_scholar_calls_per_second": 1.5,
                        "crossref_calls_per_second": 2.0,
                        "springer_calls_per_second": 0.8,
                        "arxiv_calls_per_second": 0.25,
                        "pubmed_calls_per_second": 2.8,
                        "europe_pmc_calls_per_second": 1.8,
                        "core_calls_per_second": 1.2,
                    }
                )
            }
        )

        self.assertAlmostEqual(OpenAlexClient(tuned).limiter.min_interval, 1 / 4.5)
        self.assertAlmostEqual(SemanticScholarClient(tuned).limiter.min_interval, 1 / 1.5)
        self.assertAlmostEqual(CrossrefClient(tuned).limiter.min_interval, 1 / 2.0)
        self.assertAlmostEqual(SpringerClient(tuned).limiter.min_interval, 1 / 0.8)
        self.assertAlmostEqual(ArxivClient(tuned).limiter.min_interval, 1 / 0.25)
        self.assertAlmostEqual(PubMedClient(tuned).limiter.min_interval, 1 / 2.8)
        self.assertAlmostEqual(EuropePMCClient(tuned).limiter.min_interval, 1 / 1.8)
        self.assertAlmostEqual(COREClient(tuned).limiter.min_interval, 1 / 1.2)

    def test_pubmed_search_and_xml_parsing(self) -> None:
        client = PubMedClient(self.config)
        search_payload = {"esearchresult": {"idlist": ["111", "222"]}}
        xml_payload = """
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation>
              <PMID>111</PMID>
              <Article>
                <ArticleTitle>Clinical LLM screening</ArticleTitle>
                <Abstract>
                  <AbstractText>First abstract sentence.</AbstractText>
                </Abstract>
                <AuthorList>
                  <Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author>
                </AuthorList>
                <Journal>
                  <Title>Medical AI</Title>
                  <JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue>
                </Journal>
              </Article>
            </MedlineCitation>
            <PubmedData>
              <ArticleIdList>
                <ArticleId IdType="doi">10.1000/pubmed</ArticleId>
                <ArticleId IdType="pmc">PMC123</ArticleId>
              </ArticleIdList>
            </PubmedData>
          </PubmedArticle>
        </PubmedArticleSet>
        """
        client.session = Mock()
        client.session.get.return_value = Mock(text=xml_payload, raise_for_status=Mock())
        with patch("discovery.pubmed_client.request_json", return_value=search_payload):
            results = client.search()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doi, "10.1000/pubmed")
        self.assertEqual(results[0].authors, ["Ada Lovelace"])
        self.assertTrue(results[0].open_access)

    def test_pubmed_search_continues_after_empty_query_and_stops_at_limit(self) -> None:
        config = self.config.model_copy(update={"discovery_strategy": "balanced", "pages_to_retrieve": 1, "results_per_page": 2})
        client = PubMedClient(config)
        with patch(
            "discovery.pubmed_client.request_json",
            side_effect=[None, {"esearchresult": {"idlist": ["111", "222"]}}],
        ), patch.object(client, "_fetch_batch", return_value=[PaperMetadata(title="A", source="pubmed"), PaperMetadata(title="B", source="pubmed")]):
            results = client.search()

        self.assertEqual(len(results), config.per_source_limit)

    def test_pubmed_parse_article_returns_none_for_missing_article_and_blank_title(self) -> None:
        client = PubMedClient(self.config)
        missing_article = client._parse_article(ET.fromstring("<PubmedArticle><MedlineCitation /></PubmedArticle>"))
        blank_title = client._parse_article(
            ET.fromstring(
                """
                <PubmedArticle>
                  <MedlineCitation>
                    <Article>
                      <ArticleTitle>   </ArticleTitle>
                    </Article>
                  </MedlineCitation>
                </PubmedArticle>
                """
            )
        )

        self.assertIsNone(missing_article)
        self.assertIsNone(blank_title)

    def test_pubmed_search_returns_empty_when_source_disabled(self) -> None:
        config = self.config.model_copy(update={"include_pubmed": False})
        self.assertEqual(PubMedClient(config).search(), [])

    def test_arxiv_build_search_query_and_search(self) -> None:
        config = self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1})
        client = ArxivClient(config)
        self.assertEqual(client._build_search_query("llm benchmark"), 'all:"llm benchmark"')
        invalid_config = config.model_copy(update={"boolean_operators": "weird"})
        self.assertEqual(ArxivClient(invalid_config)._build_search_query("llm benchmark"), 'all:"llm benchmark"')
        with patch(
            "discovery.arxiv_client.request_text",
            return_value="""
            <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
              <entry>
                <id>http://arxiv.org/abs/1234.5678</id>
                <title>arXiv LLM Survey</title>
                <summary>Preprint summary.</summary>
                <published>2024-02-01T00:00:00Z</published>
                <author><name>Jane Doe</name></author>
                <arxiv:doi>10.1000/arxiv</arxiv:doi>
                <arxiv:primary_category term="cs.CL" />
                <link href="https://arxiv.org/pdf/1234.5678.pdf" title="pdf" />
              </entry>
            </feed>
            """,
        ):
            results = client.search()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].venue, "arXiv")
        self.assertEqual(results[0].external_ids["category"], "cs.CL")

    def test_arxiv_search_breaks_on_empty_feed_and_per_source_limit(self) -> None:
        empty_config = self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 1, "results_per_page": 1})
        empty_client = ArxivClient(empty_config)
        with patch(
            "discovery.arxiv_client.request_text",
            return_value='<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"></feed>',
        ):
            self.assertEqual(empty_client.search(), [])

        limit_config = self.config.model_copy(update={"discovery_strategy": "precise", "pages_to_retrieve": 2, "results_per_page": 1})
        limit_client = ArxivClient(limit_config)
        feed = """
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/9999.0001</id>
            <title>arXiv Limit Paper</title>
            <summary>Preprint summary.</summary>
            <published>2024-02-01T00:00:00Z</published>
            <author><name>Jane Doe</name></author>
          </entry>
        </feed>
        """
        with patch("discovery.arxiv_client.request_text", side_effect=[feed, feed]):
            results = limit_client.search()

        self.assertEqual(len(results), limit_config.per_source_limit)
        self.assertEqual(limit_client._build_search_query("   "), 'all:"   "')


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
