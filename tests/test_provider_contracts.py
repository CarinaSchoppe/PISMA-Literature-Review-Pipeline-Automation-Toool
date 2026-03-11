"""Provider contract tests that keep all discovery adapters aligned to the shared paper model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import ResearchConfig
from discovery.arxiv_client import ArxivClient
from discovery.crossref_client import CrossrefClient
from discovery.fixture_client import FixtureDiscoveryClient
from discovery.manual_import_client import ManualImportClient
from discovery.openalex_client import OpenAlexClient
from discovery.pubmed_client import PubMedClient
from discovery.semantic_scholar_client import SemanticScholarClient
from discovery.springer_client import SpringerClient
from models.paper import PaperMetadata


class ProviderContractTests(unittest.TestCase):
    """Verify that every provider returns normalized paper records through the same contract."""

    def setUp(self) -> None:
        self.config = ResearchConfig(
            research_topic="Large language models",
            search_keywords=["survey", "benchmark"],
            pages_to_retrieve=1,
            results_per_page=1,
            openalex_enabled=True,
            semantic_scholar_enabled=True,
            crossref_enabled=True,
            include_pubmed=True,
            fixture_data_path=Path("tests/fixtures/offline_papers.json"),
            disable_progress_bars=True,
            api_settings={
                "springer_api_key": "springer-key",
            },
        ).finalize()

    def test_api_search_clients_return_normalized_papers(self) -> None:
        openalex_payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "OpenAlex Paper",
                    "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                    "abstract_inverted_index": {"hello": [0]},
                    "publication_year": 2024,
                    "primary_location": {"source": {"display_name": "OpenAlex Venue"}},
                    "ids": {"doi": "https://doi.org/10.1000/openalex"},
                    "cited_by_count": 1,
                    "referenced_works": [],
                    "open_access": {"is_oa": True},
                }
            ]
        }
        crossref_payload = {
            "message": {
                "items": [
                    {
                        "title": ["Crossref Paper"],
                        "author": [{"given": "Grace", "family": "Hopper"}],
                        "container-title": ["Crossref Venue"],
                        "DOI": "10.1000/crossref",
                        "is-referenced-by-count": 2,
                        "reference": [],
                    }
                ]
            }
        }
        semantic_payload = {
            "data": [
                {
                    "paperId": "S1",
                    "title": "Semantic Paper",
                    "abstract": "Semantic abstract",
                    "year": 2025,
                    "venue": "Semantic Venue",
                    "authors": [{"name": "Claude Shannon"}],
                    "citationCount": 4,
                    "referenceCount": 1,
                    "externalIds": {"DOI": "10.1000/semantic"},
                }
            ]
        }
        springer_payload = {
            "records": [
                {
                    "title": "Springer Paper",
                    "creators": [{"creator": "Margaret Hamilton"}],
                    "publicationDate": "2024-02-02",
                    "publicationName": "Springer Venue",
                    "doi": "10.1000/springer",
                    "url": [{"format": "pdf", "value": "https://example.org/springer.pdf"}],
                    "openaccess": "true",
                }
            ]
        }

        with patch("discovery.openalex_client.request_json", return_value=openalex_payload):
            openalex_results = OpenAlexClient(self.config).search()
        with patch("discovery.crossref_client.request_json", return_value=crossref_payload):
            crossref_results = CrossrefClient(self.config).search()
        with patch("discovery.semantic_scholar_client.request_json", return_value=semantic_payload):
            semantic_results = SemanticScholarClient(self.config).search()
        with patch("discovery.springer_client.request_json", return_value=springer_payload):
            springer_results = SpringerClient(self.config).search()

        for expected_source, results in {
            "openalex": openalex_results,
            "crossref": crossref_results,
            "semantic_scholar": semantic_results,
            "springer": springer_results,
        }.items():
            with self.subTest(source=expected_source):
                self.assert_provider_contract(results[0], expected_source)

    def test_feed_and_xml_providers_return_normalized_papers(self) -> None:
        arxiv_feed = """
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/1234.5678</id>
            <title>arXiv Paper</title>
            <summary>Preprint summary.</summary>
            <published>2024-02-01T00:00:00Z</published>
            <author><name>Jane Doe</name></author>
            <arxiv:doi>10.1000/arxiv</arxiv:doi>
            <link href="https://arxiv.org/pdf/1234.5678.pdf" title="pdf" />
          </entry>
        </feed>
        """
        pubmed_search_payload = {"esearchresult": {"idlist": ["111"]}}
        pubmed_fetch_xml = """
        <PubmedArticleSet>
          <PubmedArticle>
            <MedlineCitation>
              <PMID>111</PMID>
              <Article>
                <ArticleTitle>PubMed Paper</ArticleTitle>
                <Abstract><AbstractText>Clinical abstract.</AbstractText></Abstract>
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

        with patch("discovery.arxiv_client.request_text", return_value=arxiv_feed):
            arxiv_results = ArxivClient(self.config).search()

        pubmed_client = PubMedClient(self.config)
        pubmed_client.session = Mock()
        pubmed_client.session.get.return_value = Mock(text=pubmed_fetch_xml, raise_for_status=Mock())
        with patch("discovery.pubmed_client.request_json", return_value=pubmed_search_payload):
            pubmed_results = pubmed_client.search()

        self.assert_provider_contract(arxiv_results[0], "arxiv")
        self.assert_provider_contract(pubmed_results[0], "pubmed")

    def test_fixture_and_manual_import_providers_return_normalized_papers(self) -> None:
        fixture_client = FixtureDiscoveryClient(self.config)
        fixture_results = fixture_client.search()
        self.assert_provider_contract(fixture_results[0], "fixture")

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manual.csv"
            csv_path.write_text(
                "title,authors,abstract,year,venue,doi,source,open_access\n"
                "Manual Paper,Alice Example;Bob Example,Manual abstract,2024,Manual Venue,10.1000/manual,manual_import,true\n",
                encoding="utf-8",
            )
            manual_results = ManualImportClient(self.config, path=csv_path, source_name="manual_import").search()

        self.assert_provider_contract(manual_results[0], "manual_import")

    def test_citation_contracts_return_normalized_papers(self) -> None:
        openalex_payload = {
            "id": "https://openalex.org/W1",
            "display_name": "OpenAlex Paper",
            "authorships": [],
            "abstract_inverted_index": {"openalex": [0]},
            "publication_year": 2024,
            "primary_location": {"source": {"display_name": "OpenAlex Venue"}},
            "ids": {"doi": "https://doi.org/10.1000/openalex"},
            "cited_by_count": 1,
            "referenced_works": ["WREF1"],
            "open_access": {"is_oa": False},
        }
        reference_payload = {
            "id": "https://openalex.org/WREF1",
            "display_name": "Reference Paper",
            "authorships": [],
            "abstract_inverted_index": {"reference": [0]},
            "publication_year": 2023,
            "primary_location": {"source": {"display_name": "Reference Venue"}},
            "ids": {"doi": "https://doi.org/10.1000/reference"},
            "cited_by_count": 0,
            "referenced_works": [],
            "open_access": {"is_oa": False},
        }
        citations_payload = {
            "results": [
                {
                    "id": "https://openalex.org/WCIT1",
                    "display_name": "Citation Paper",
                    "authorships": [],
                    "abstract_inverted_index": {"citation": [0]},
                    "publication_year": 2025,
                    "primary_location": {"source": {"display_name": "Citation Venue"}},
                    "ids": {"doi": "https://doi.org/10.1000/citation"},
                    "cited_by_count": 0,
                    "referenced_works": [],
                    "open_access": {"is_oa": False},
                }
            ]
        }

        def fake_request_json(_session, _method, url, **kwargs):
            params = kwargs.get("params") or {}
            if str(url).endswith("/WREF1"):
                return reference_payload
            if str(url).endswith("/W1"):
                return openalex_payload
            if str(params.get("filter", "")).startswith("cites:"):
                return citations_payload
            return {"results": [openalex_payload]}

        paper = PaperMetadata(title="OpenAlex Paper", doi="10.1000/openalex", source="test")
        with patch("discovery.openalex_client.request_json", side_effect=fake_request_json):
            client = OpenAlexClient(self.config)
            references = client.fetch_references(paper)
            citations = client.fetch_citations(paper)

        self.assert_provider_contract(references[0], "openalex")
        self.assert_provider_contract(citations[0], "openalex")

    def assert_provider_contract(self, paper: PaperMetadata, expected_source: str) -> None:
        """Assert the normalized paper fields expected from every provider adapter."""

        self.assertIsInstance(paper, PaperMetadata)
        self.assertEqual(paper.source, expected_source)
        self.assertEqual(paper.query_key, self.config.query_key)
        self.assertTrue(paper.title.strip())
        self.assertIsInstance(paper.authors, list)
        self.assertIsInstance(paper.raw_payload, dict)
        self.assertIsInstance(paper.external_ids, dict)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
