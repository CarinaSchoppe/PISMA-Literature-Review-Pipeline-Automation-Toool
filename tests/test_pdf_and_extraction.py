"""Tests for PDF lookup/downloading and full-text extraction helpers."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from acquisition.full_text_extractor import FullTextExtractor
from acquisition.pdf_fetcher import PDFFetcher
from config import ResearchConfig
from models.paper import PaperMetadata


class FakeBinaryResponse:
    """Simple binary response object for PDF download tests."""

    def __init__(self, *, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.headers = headers
        self._chunks = chunks

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002 - mimic requests API
        yield from self._chunks


class FullTextExtractionAndPDFTests(unittest.TestCase):
    """Verify PDF enrichment behavior without reaching external services."""

    def _config(self, root: Path) -> ResearchConfig:
        return ResearchConfig(
            research_topic="Test",
            search_keywords=["llm"],
            openalex_enabled=False,
            semantic_scholar_enabled=False,
            crossref_enabled=False,
            include_pubmed=False,
            data_dir=root / "data",
            papers_dir=root / "papers",
            results_dir=root / "results",
            database_path=root / "data" / "db.sqlite",
        ).finalize()

    def test_fetch_for_paper_reads_unpaywall_and_optionally_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            config.api_settings.unpaywall_email = "carina@example.com"
            paper = PaperMetadata(title="Example", doi="10.1000/example", source="test")
            fetcher = PDFFetcher(config)

            with patch("acquisition.pdf_fetcher.request_json", return_value={"is_oa": True, "best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"}}), patch.object(
                PDFFetcher, "download_pdf", return_value="papers/example.pdf"
            ) as download_mock:
                enriched = fetcher.fetch_for_paper(paper, download=True)

            self.assertEqual(enriched.pdf_link, "https://example.org/paper.pdf")
            self.assertEqual(enriched.pdf_path, "papers/example.pdf")
            self.assertTrue(enriched.open_access)
            download_mock.assert_called_once()

    def test_download_pdf_reuses_existing_file_rejects_html_and_writes_valid_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fetcher = PDFFetcher(self._config(root))
            paper = PaperMetadata(title="My Paper", source="test")

            existing = root / "papers" / "my-paper.pdf"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(b"%PDF existing")
            self.assertEqual(fetcher.download_pdf(paper, "https://example.org/file.pdf", target_dir=root / "papers"), str(existing))

            existing.unlink()
            with patch(
                "acquisition.pdf_fetcher.request_content",
                return_value=FakeBinaryResponse(headers={"Content-Type": "text/html"}, chunks=[b"<htm", b"ignored"]),
            ):
                self.assertIsNone(fetcher.download_pdf(paper, "https://example.org/file.pdf", target_dir=root / "papers"))

            with patch(
                "acquisition.pdf_fetcher.request_content",
                return_value=FakeBinaryResponse(
                    headers={"Content-Type": "application/pdf"},
                    chunks=[b"%PDF-1.7", b" content"],
                ),
            ):
                output = fetcher.download_pdf(paper, "https://example.org/file.pdf", target_dir=root / "papers")

            self.assertIsNotNone(output)
            self.assertTrue(Path(str(output)).exists())
            self.assertTrue(Path(str(output)).read_bytes().startswith(b"%PDF"))

    def test_full_text_extractor_handles_missing_runtime_missing_files_success_and_failure(self) -> None:
        extractor = FullTextExtractor(max_chars=12)

        self.assertIsNone(extractor.extract_excerpt(None))
        self.assertIsNone(extractor.extract_excerpt("missing.pdf"))

        with patch("builtins.__import__", side_effect=ImportError("no pypdf")):
            self.assertIsNone(extractor.extract_excerpt("missing.pdf"))

        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF")

            class FakePage:
                def __init__(self, text: str) -> None:
                    self._text = text

                def extract_text(self) -> str:
                    return self._text

            fake_module = types.SimpleNamespace(PdfReader=lambda _path: types.SimpleNamespace(pages=[FakePage("abcdefghijklm"), FakePage("tail")]))
            with patch.dict("sys.modules", {"pypdf": fake_module}):
                excerpt = extractor.extract_excerpt(pdf_path)
            self.assertEqual(excerpt, "abcdefghijkl")

            def raise_reader(_path: str):
                raise RuntimeError("broken pdf")

            fake_module_error = types.SimpleNamespace(PdfReader=raise_reader)
            with patch.dict("sys.modules", {"pypdf": fake_module_error}):
                self.assertIsNone(extractor.extract_excerpt(pdf_path))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
