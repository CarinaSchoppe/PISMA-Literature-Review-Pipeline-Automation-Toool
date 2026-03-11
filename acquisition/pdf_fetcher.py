"""PDF lookup and download helpers built around Unpaywall and direct OA links."""

from __future__ import annotations

import logging
from pathlib import Path

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_content, request_json
from utils.text_processing import ensure_parent_directory, slugify_filename

LOGGER = logging.getLogger(__name__)


class PDFFetcher:
    """Resolve open-access PDF URLs and optionally download them to disk."""

    BASE_URL = "https://api.unpaywall.org/v2"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.unpaywall_calls_per_second)

    def fetch_for_paper(
            self,
            paper: PaperMetadata,
            *,
            download: bool | None = None,
            target_dir: Path | None = None,
    ) -> PaperMetadata:
        """Enrich one paper with PDF metadata and an optional downloaded file path."""

        pdf_link = paper.pdf_link
        open_access = paper.open_access

        if paper.doi and self.config.api_settings.unpaywall_email:
            payload = request_json(
                self.session,
                "GET",
                f"{self.BASE_URL}/{paper.doi}",
                limiter=self.limiter,
                timeout=self.config.request_timeout_seconds,
                params={"email": self.config.api_settings.unpaywall_email},
            )
            if payload:
                best_location = payload.get("best_oa_location") or {}
                pdf_link = pdf_link or best_location.get("url_for_pdf") or best_location.get("url")
                open_access = bool(payload.get("is_oa")) or open_access

        pdf_path = paper.pdf_path
        should_download = self.config.download_pdfs if download is None else download
        if should_download and pdf_link:
            pdf_path = self.download_pdf(paper, pdf_link, target_dir=target_dir)

        return paper.model_copy(
            update={
                "pdf_link": pdf_link,
                "pdf_path": pdf_path,
                "open_access": open_access,
            }
        )

    def download_pdf(self, paper: PaperMetadata, url: str, *, target_dir: Path | None = None) -> str | None:
        """Download a PDF if the response looks like a valid PDF stream."""

        filename_root = paper.doi or paper.title
        filename = f"{slugify_filename(filename_root)}.pdf"
        target = (target_dir or Path(self.config.papers_dir)) / filename
        if target.exists():
            return str(target)

        response = request_content(
            self.session,
            url,
            limiter=self.limiter,
            timeout=max(60, self.config.request_timeout_seconds),
            stream=True,
            headers={"Accept": "application/pdf,*/*"},
            allow_redirects=True,
        )
        if response is None:
            return None

        content_type = response.headers.get("Content-Type", "").lower()
        preview = b""
        # Some providers mislabel PDFs, so inspect the file header before writing HTML to disk.
        if "pdf" not in content_type and "octet-stream" not in content_type:
            preview = next(response.iter_content(chunk_size=4), b"")
            if preview != b"%PDF":
                LOGGER.warning("Skipping non-PDF response for %s", paper.title)
                return None

        ensure_parent_directory(target)
        with target.open("wb") as handle:
            if preview:
                handle.write(preview)
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return str(target)
