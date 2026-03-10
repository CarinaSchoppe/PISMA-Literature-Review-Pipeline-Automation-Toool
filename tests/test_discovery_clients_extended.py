"""Extended tests for discovery client pagination, parsing, and helper branches."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from config import ResearchConfig
from discovery.arxiv_client import ArxivClient
from discovery.crossref_client import CrossrefClient
from discovery.openalex_client import OpenAlexClient
from discovery.pubmed_client import PubMedClient
from discovery.semantic_scholar_client import SemanticScholarClient
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


if __name__ == "__main__":
    unittest.main()
