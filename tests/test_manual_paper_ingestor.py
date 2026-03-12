"""Tests for manual paper ingestion from DOI links, landing pages, and local PDFs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from acquisition.manual_paper_ingestor import ManualPaperIngestor
from config import ResearchConfig
from models.paper import PaperMetadata


class ManualPaperIngestorTests(unittest.TestCase):
    """Exercise the manual link/PDF resolver without live network calls."""

    def _config(self, root: Path) -> ResearchConfig:
        return ResearchConfig(
            research_topic="AI-assisted literature review",
            search_keywords=["llm", "systematic review"],
            data_dir=root / "data",
            papers_dir=root / "papers",
            results_dir=root / "results",
            database_path=root / "data" / "manual.db",
        ).finalize()

    def test_ingest_link_uses_crossref_for_doi_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            ingestor = ManualPaperIngestor(config)
            payload = {
                "message": {
                    "title": ["Manual DOI Paper"],
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "container-title": ["Journal"],
                    "DOI": "10.1000/test",
                    "abstract": "<jats:p>Paper abstract</jats:p>",
                    "link": [{"content-type": "application/pdf", "URL": "https://example.org/paper.pdf"}],
                }
            }
            with patch("acquisition.manual_paper_ingestor.request_json", return_value=payload):
                paper = ingestor.ingest_link("https://doi.org/10.1000/test")

        self.assertEqual(paper.title, "Manual DOI Paper")
        self.assertEqual(paper.doi, "10.1000/test")
        self.assertEqual(paper.external_ids.get("manual_url"), "https://doi.org/10.1000/test")

    def test_ingest_link_can_build_metadata_from_landing_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            ingestor = ManualPaperIngestor(config)
            html = """
            <html>
              <head>
                <title>Landing Page Paper</title>
                <meta name="description" content="A practical paper summary.">
                <meta name="citation_pdf_url" content="/paper.pdf">
              </head>
            </html>
            """
            pdf_paper = PaperMetadata(title="Landing Page Paper", source="manual_link_pdf", pdf_path="papers/manual.pdf")
            with patch("acquisition.manual_paper_ingestor.request_text", return_value=html), patch.object(
                ingestor, "_download_pdf", return_value=Path(temp_dir) / "paper.pdf"
            ), patch.object(ingestor, "_paper_from_local_pdf", return_value=pdf_paper):
                paper = ingestor.ingest_link("https://example.org/paper")

        self.assertEqual(paper.title, "Landing Page Paper")
        self.assertEqual(paper.external_ids.get("manual_url"), "https://example.org/paper")

    def test_ingest_pdf_uses_excerpt_and_can_enrich_via_doi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            pdf_path = root / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 sample")
            ingestor = ManualPaperIngestor(config)
            crossref_payload = {
                "message": {
                    "title": ["Extracted PDF Paper"],
                    "author": [{"given": "Grace", "family": "Hopper"}],
                    "container-title": ["Archive"],
                    "DOI": "10.5555/pdf-paper",
                }
            }
            excerpt = "Extracted PDF Paper\nThis paper uses DOI 10.5555/pdf-paper and studies LLM screening."
            with patch.object(ingestor.extractor, "extract_excerpt", return_value=excerpt), patch(
                "acquisition.manual_paper_ingestor.request_json",
                return_value=crossref_payload,
            ):
                paper = ingestor.ingest_pdf(pdf_path)

        self.assertEqual(paper.title, "Extracted PDF Paper")
        self.assertEqual(paper.doi, "10.5555/pdf-paper")
        self.assertEqual(paper.pdf_path, str(pdf_path))

    def test_ingest_link_rejects_blank_input_and_missing_crossref_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            ingestor = ManualPaperIngestor(config)
            with self.assertRaisesRegex(ValueError, "paper link is required"):
                ingestor.ingest_link("   ")
            with patch("acquisition.manual_paper_ingestor.request_json", return_value={"message": {}}):
                with self.assertRaisesRegex(ValueError, "No Crossref metadata"):
                    ingestor.ingest_link("10.1000/test")

    def test_ingest_link_handles_arxiv_and_missing_arxiv_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            ingestor = ManualPaperIngestor(config)
            arxiv_paper = PaperMetadata(title="Arxiv Paper", source="arxiv")
            with patch("acquisition.manual_paper_ingestor.request_text", return_value="<feed/>"), patch(
                "discovery.arxiv_client.ArxivClient._parse_feed",
                return_value=[arxiv_paper],
            ):
                paper = ingestor.ingest_link("https://arxiv.org/abs/2501.12345")
            self.assertEqual(paper.title, "Arxiv Paper")
            self.assertEqual(paper.external_ids.get("manual_url"), "https://arxiv.org/abs/2501.12345")

            with patch("acquisition.manual_paper_ingestor.request_text", return_value=""):
                with self.assertRaisesRegex(ValueError, "No arXiv metadata"):
                    ingestor.ingest_link("arxiv:2501.12345")
            with patch("acquisition.manual_paper_ingestor.request_text", return_value="<feed/>"), patch(
                "discovery.arxiv_client.ArxivClient._parse_feed",
                return_value=[],
            ):
                with self.assertRaisesRegex(ValueError, "No arXiv metadata"):
                    ingestor.ingest_link("2501.12345")

    def test_landing_page_and_local_pdf_cover_fallback_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            ingestor = ManualPaperIngestor(config)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(b"%PDF")

            html = """
            <html><head>
                <meta name="citation_title" content="Landing title">
                <meta name="description" content="desc">
                <meta name="citation_pdf_url" content="/paper.pdf">
                <meta name="citation_doi" content="10.1000/landing">
            </head></html>
            """
            with patch("acquisition.manual_paper_ingestor.request_text", return_value=html), patch.object(
                ingestor, "_paper_from_doi", side_effect=RuntimeError("boom")
            ), patch.object(
                ingestor, "_download_pdf", return_value=pdf_path
            ), patch.object(
                ingestor,
                "_paper_from_local_pdf",
                return_value=PaperMetadata(title="PDF title", source="manual_link_pdf", pdf_path=str(pdf_path)),
            ):
                paper = ingestor.ingest_link("https://example.org/paper")
            self.assertEqual(paper.title, "Landing title")
            self.assertEqual(paper.pdf_path, str(pdf_path))
            self.assertEqual(paper.external_ids.get("manual_url"), "https://example.org/paper")

            with patch.object(ingestor.extractor, "extract_excerpt", return_value="No doi excerpt"), patch.object(
                ingestor, "_paper_from_doi", side_effect=AssertionError("should not enrich")
            ):
                local_paper = ingestor.ingest_pdf(pdf_path)
            self.assertEqual(local_paper.pdf_path, str(pdf_path))
            self.assertEqual(local_paper.source, "manual_local_pdf")

            with patch.object(
                ingestor.extractor,
                "extract_excerpt",
                return_value="Interesting title\nDOI 10.2000/testdoi present",
            ), patch.object(ingestor, "_paper_from_doi", side_effect=RuntimeError("boom")):
                enriched_fallback = ingestor.ingest_pdf(pdf_path)
            self.assertEqual(enriched_fallback.doi, "10.2000/testdoi")

            with patch("acquisition.manual_paper_ingestor.request_text", return_value=""), self.assertRaisesRegex(
                ValueError,
                "No metadata could be downloaded",
            ):
                ingestor.ingest_link("https://example.org/empty")

            with patch("acquisition.manual_paper_ingestor.request_text", return_value=html), patch.object(
                ingestor,
                "_download_pdf",
                side_effect=RuntimeError("pdf blocked"),
            ):
                warning_only = ingestor.ingest_link("https://example.org/paper-warning")
            self.assertEqual(warning_only.title, "Landing title")

    def test_download_and_html_helpers_cover_non_pdf_and_filename_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            ingestor = ManualPaperIngestor(config)

            html = """
            <html><head>
                <meta property="og:title" content="OG Title">
                <meta property="og:description" content="OG Description">
            </head><body><a href="/download/paper.pdf">PDF</a></body></html>
            """
            self.assertEqual(ingestor._extract_html_title(html), "OG Title")
            self.assertEqual(ingestor._extract_meta_content(html, "og:description"), "OG Description")
            self.assertEqual(
                ingestor._extract_pdf_link(html, base_url="https://example.org/page"),
                "https://example.org/download/paper.pdf",
            )
            self.assertIsNone(ingestor._extract_pdf_link("<html></html>", base_url="https://example.org/page"))
            self.assertEqual(
                ingestor._infer_title(Path("sample_name.pdf"), "Short\nA much longer inferred title line for the paper"),
                "A much longer inferred title line for the paper",
            )
            self.assertEqual(ingestor._infer_title(Path("sample_name.pdf"), "tiny"), "sample name")
            self.assertTrue(ingestor._looks_like_pdf_link("https://example.org/file.pdf"))
            self.assertFalse(ingestor._looks_like_pdf_link("https://example.org/file"))
            self.assertEqual(ingestor._clean_html_text("<b>Hello</b> &amp; world"), "Hello & world")

            response = Mock()
            response.headers = {"Content-Type": "application/pdf"}
            ingestor._ensure_pdf_response(response, "https://example.org/file")
            response.headers = {"Content-Type": "text/html"}
            with self.assertRaisesRegex(ValueError, "did not return a PDF"):
                ingestor._ensure_pdf_response(response, "https://example.org/file")

            mock_response = Mock()
            mock_response.headers = {"Content-Type": "application/pdf"}
            mock_response.iter_content.return_value = [b"part1", b"", b"part2"]
            mock_response.raise_for_status.return_value = None
            with patch.object(ingestor.session, "get", return_value=mock_response):
                first = ingestor._download_pdf("https://example.org/file.pdf", preferred_stem="My Paper")
                second = ingestor._download_pdf("https://example.org/file.pdf", preferred_stem="My Paper")
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertNotEqual(first, second)

    def test_ingest_pdf_raises_for_missing_local_file_and_direct_pdf_url_uses_pdf_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(root)
            ingestor = ManualPaperIngestor(config)

            with self.assertRaisesRegex(FileNotFoundError, "Paper file not found"):
                ingestor.ingest_pdf(root / "missing.pdf")

            local_pdf = root / "downloaded.pdf"
            local_pdf.write_bytes(b"%PDF")
            pdf_paper = PaperMetadata(
                title="Downloaded PDF",
                source="manual_pdf_url",
                pdf_path=str(local_pdf),
                raw_payload={},
            )
            with patch.object(ingestor, "_download_pdf", return_value=local_pdf) as download_pdf, patch.object(
                ingestor,
                "_paper_from_local_pdf",
                return_value=pdf_paper,
            ) as paper_from_local_pdf:
                paper = ingestor.ingest_link("https://example.org/download?id=1&download=true")

            download_pdf.assert_called_once()
            paper_from_local_pdf.assert_called_once_with(
                local_pdf,
                source="manual_pdf_url",
                source_url="https://example.org/download?id=1&download=true",
            )
            self.assertEqual(paper.title, "Downloaded PDF")
