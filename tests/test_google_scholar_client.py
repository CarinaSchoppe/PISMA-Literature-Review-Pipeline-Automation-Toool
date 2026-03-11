"""Tests for Google Scholar page traversal, bounds, and result parsing."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from config import ResearchConfig
from discovery.google_scholar_client import GoogleScholarClient


class GoogleScholarClientTests(unittest.TestCase):
    """Verify bounded Scholar page retrieval and metadata parsing."""

    def _config(self, **overrides) -> ResearchConfig:
        values = {
            "research_topic": "AI governance",
            "search_keywords": ["generative AI", "governance"],
            "google_scholar_enabled": True,
            "pages_to_retrieve": 1,
            "google_scholar_pages": 3,
            "google_scholar_results_per_page": 2,
            "results_per_page": 2,
            "max_papers_to_analyze": 20,
            "include_pubmed": False,
            "discovery_strategy": "precise",
        }
        values.update(overrides)
        return ResearchConfig(**values).finalize()

    def test_search_respects_page_depth_and_parses_result_metadata(self) -> None:
        config = self._config(google_scholar_pages=2, google_scholar_results_per_page=2)
        client = GoogleScholarClient(config)
        page_one = '''
        <div class="gs_r gs_or gs_scl">
            <div class="gs_or_ggsm"><a href="https://example.org/paper-a.pdf">[PDF]</a></div>
            <h3 class="gs_rt"><a href="https://example.org/paper-a">AI Governance in Hospitals</a></h3>
            <div class="gs_a">Ada Lovelace, Grace Hopper - Journal of AI Policy - 2024</div>
            <div class="gs_rs">A study of AI governance and deployment in healthcare systems. DOI 10.1000/xyz123</div>
        </div>
        <div class="gs_r gs_or gs_scl">
            <h3 class="gs_rt"><a href="https://example.org/paper-b">LLM Deployment Oversight</a></h3>
            <div class="gs_a">Katherine Johnson - Governance Review - 2023</div>
            <div class="gs_rs">Policy and oversight implications for LLM deployment.</div>
        </div>
        '''
        page_two = '''
        <div class="gs_r gs_or gs_scl">
            <h3 class="gs_rt"><a href="https://example.org/paper-c">Clinical imaging biomarkers</a></h3>
            <div class="gs_a">Medical Author - Biomarker Journal - 2022</div>
            <div class="gs_rs">A medical imaging study.</div>
        </div>
        '''

        with patch("discovery.google_scholar_client.request_text", side_effect=[page_one, page_two]) as request_mock:
            papers = client.search()

        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0].title, "AI Governance in Hospitals")
        self.assertEqual(papers[0].authors, ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(papers[0].year, 2024)
        self.assertEqual(papers[0].doi, "10.1000/xyz123")
        self.assertEqual(papers[0].pdf_link, "https://example.org/paper-a.pdf")
        self.assertEqual(papers[0].raw_payload["result_url"], "https://example.org/paper-a")
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[0].kwargs["params"]["start"], 0)
        self.assertEqual(request_mock.call_args_list[1].kwargs["params"]["start"], 2)

    def test_search_continues_after_blank_page_and_honors_page_limit(self) -> None:
        config = self._config(google_scholar_pages=3, google_scholar_results_per_page=1)
        client = GoogleScholarClient(config)
        first_page = '<div class="gs_r gs_or"><h3 class="gs_rt"><a href="https://example.org/a">Paper A</a></h3><div class="gs_a">Author - Venue - 2024</div><div class="gs_rs">Abstract A</div></div>'
        third_page = '<div class="gs_r gs_or"><h3 class="gs_rt"><a href="https://example.org/b">Paper B</a></h3><div class="gs_a">Author - Venue - 2023</div><div class="gs_rs">Abstract B</div></div>'

        with patch("discovery.google_scholar_client.request_text", side_effect=[first_page, None, third_page]) as request_mock:
            papers = client.search()

        self.assertEqual([paper.title for paper in papers], ["Paper A", "Paper B"])
        self.assertEqual(request_mock.call_count, 3)

    def test_search_stops_cleanly_when_stop_callback_is_triggered(self) -> None:
        config = self._config(google_scholar_pages=3, google_scholar_results_per_page=1)
        stop_calls = {"count": 0}

        def should_stop() -> bool:
            stop_calls["count"] += 1
            return stop_calls["count"] >= 3

        client = GoogleScholarClient(config, should_stop=should_stop)
        first_page = '<div class="gs_r gs_or"><h3 class="gs_rt"><a href="https://example.org/a">Paper A</a></h3><div class="gs_a">Author - Venue - 2024</div><div class="gs_rs">Abstract A</div></div>'

        with patch("discovery.google_scholar_client.request_text", return_value=first_page) as request_mock:
            papers = client.search()

        self.assertEqual([paper.title for paper in papers], ["Paper A"])
        self.assertEqual(request_mock.call_count, 1)

    def test_parse_result_block_handles_plain_title_without_link(self) -> None:
        client = GoogleScholarClient(self._config())
        block = '''
        <div class="gs_r gs_or">
            <h3 class="gs_rt">[CITATION] Governance without direct link</h3>
            <div class="gs_a">Author A, Author B - Venue - 2021</div>
            <div class="gs_rs">Snippet text.</div>
        </div>
        '''

        paper = client._parse_result_block(block)

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.title, "[CITATION] Governance without direct link")
        self.assertIsNone(paper.raw_payload["result_url"])
        self.assertEqual(paper.year, 2021)

    def test_google_scholar_page_bounds_reject_non_positive_values(self) -> None:
        with self.assertRaises(ValueError):
            self._config(google_scholar_pages=0, google_scholar_results_per_page=0)

    def test_google_scholar_page_bounds_reject_values_above_supported_range(self) -> None:
        with self.assertRaises(ValueError):
            self._config(google_scholar_pages=101)
