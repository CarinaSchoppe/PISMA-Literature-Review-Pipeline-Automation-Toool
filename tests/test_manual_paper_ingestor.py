"""Tests for manual paper ingestion from DOI links, landing pages, and local PDFs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
