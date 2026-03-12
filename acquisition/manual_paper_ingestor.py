"""Resolve manually supplied paper links or local PDFs into pipeline paper metadata."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from requests import Response

from acquisition.full_text_extractor import FullTextExtractor
from config import ResearchConfig
from discovery.arxiv_client import ArxivClient
from discovery.crossref_client import CrossrefClient
from models.paper import PaperMetadata
from utils.http import build_session, request_json, request_text
from utils.text_processing import canonical_doi, normalize_title

LOGGER = logging.getLogger(__name__)


class ManualPaperIngestor:
    """Build paper metadata from manually supplied links or already-downloaded PDFs."""

    DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
    ARXIV_PATTERN = re.compile(
        r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)?(?P<identifier>\d{4}\.\d{4,5}(?:v\d+)?)",
        re.IGNORECASE,
    )
    META_PATTERN = re.compile(
        r'<meta[^>]+(?:name|property)=["\'](?P<name>[^"\']+)["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
        re.IGNORECASE,
    )
    HREF_PATTERN = re.compile(r'href=["\'](?P<href>[^"\']+)["\']', re.IGNORECASE)
    TITLE_PATTERN = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.extractor = FullTextExtractor(max_chars=config.full_text_max_chars)
        self.session = build_session(
            "PRISMA-Literature-Review/1.0",
            extra_headers={"Accept": "text/html,application/json,application/pdf;q=0.9,*/*;q=0.8"},
        )

    def ingest_link(self, link: str) -> PaperMetadata:
        """Resolve one DOI, arXiv page, PDF URL, or general landing page into paper metadata."""

        normalized_link = str(link or "").strip()
        if not normalized_link:
            raise ValueError("A paper link is required.")

        doi_candidate = canonical_doi(normalized_link)
        doi = doi_candidate if doi_candidate and self.DOI_PATTERN.fullmatch(doi_candidate) else ""
        if doi:
            paper = self._paper_from_doi(doi)
            return self._attach_manual_url_metadata(paper, normalized_link)

        arxiv_identifier = self._extract_arxiv_identifier(normalized_link)
        if arxiv_identifier:
            paper = self._paper_from_arxiv(arxiv_identifier)
            return self._attach_manual_url_metadata(paper, normalized_link)

        if self._looks_like_pdf_link(normalized_link):
            pdf_path = self._download_pdf(normalized_link)
            return self._paper_from_local_pdf(pdf_path, source="manual_pdf_url", source_url=normalized_link)

        return self._paper_from_landing_page(normalized_link)

    def ingest_pdf(self, pdf_path: str | Path) -> PaperMetadata:
        """Resolve a user-selected local PDF into paper metadata and preview text."""

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"Paper file not found: {path}")
        return self._paper_from_local_pdf(path, source="manual_local_pdf")

    def _paper_from_doi(self, doi: str) -> PaperMetadata:
        """Fetch metadata for one DOI through Crossref."""

        client = CrossrefClient(self.config)
        payload = request_json(
            client.session,
            "GET",
            f"{client.BASE_URL}/{doi}",
            limiter=client.limiter,
            timeout=self.config.request_timeout_seconds,
        )
        item = (payload or {}).get("message") or {}
        if not item or not item.get("title"):
            raise ValueError(f"No Crossref metadata was found for DOI {doi}.")
        paper = client._parse_item(item)
        return paper.model_copy(
            update={
                "query_key": self.config.query_key,
                "source": paper.source or "crossref",
                "raw_payload": {"manual_entry_kind": "doi", **paper.raw_payload},
            }
        )

    def _paper_from_arxiv(self, identifier: str) -> PaperMetadata:
        """Fetch metadata for one arXiv identifier through the public Atom API."""

        client = ArxivClient(self.config)
        payload = request_text(
            client.session,
            "GET",
            client.BASE_URL,
            limiter=client.limiter,
            timeout=max(60, self.config.request_timeout_seconds),
            params={
                "id_list": identifier,
                "max_results": 1,
            },
        )
        if not payload:
            raise ValueError(f"No arXiv metadata was found for identifier {identifier}.")
        papers = client._parse_feed(payload)
        if not papers:
            raise ValueError(f"No arXiv metadata was found for identifier {identifier}.")
        paper = papers[0]
        return paper.model_copy(
            update={
                "query_key": self.config.query_key,
                "source": "arxiv",
                "raw_payload": {"manual_entry_kind": "arxiv", **paper.raw_payload},
            }
        )

    def _paper_from_landing_page(self, link: str) -> PaperMetadata:
        """Resolve a general paper page by scraping lightweight metadata and optional PDF hints."""

        payload = request_text(
            self.session,
            "GET",
            link,
            timeout=self.config.request_timeout_seconds,
            use_cache=False,
        )
        if not payload:
            raise ValueError(f"No metadata could be downloaded from {link}.")

        title = self._extract_html_title(payload)
        abstract = self._extract_meta_content(payload, "description") or self._extract_meta_content(payload, "og:description")
        doi = canonical_doi(self._extract_doi(payload))
        pdf_link = self._extract_pdf_link(payload, base_url=link)

        page_paper = PaperMetadata(
            query_key=self.config.query_key,
            title=title or link,
            abstract=abstract or "",
            source="manual_link",
            pdf_link=pdf_link,
            open_access=bool(pdf_link),
            external_ids={"manual_url": link, "doi": doi or ""},
            raw_payload={
                "manual_entry_kind": "landing_page",
                "manual_entry_url": link,
                "html_title": title or "",
                "meta_description": abstract or "",
            },
        )

        enriched = page_paper
        if doi:
            try:
                enriched = self._paper_from_doi(doi).merge_with(page_paper)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Could not enrich manual link via DOI %s: %s", doi, exc)

        pdf_path: Path | None = None
        if pdf_link:
            try:
                pdf_path = self._download_pdf(pdf_link, preferred_stem=enriched.title)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Could not download PDF for manual link %s: %s", link, exc)

        if pdf_path is not None:
            pdf_paper = self._paper_from_local_pdf(pdf_path, source="manual_link_pdf", source_url=pdf_link)
            enriched = enriched.merge_with(pdf_paper)

        return self._attach_manual_url_metadata(enriched, link)

    def _paper_from_local_pdf(
        self,
        pdf_path: Path,
        *,
        source: str,
        source_url: str | None = None,
    ) -> PaperMetadata:
        """Build paper metadata from a local PDF and enrich it through DOI metadata when possible."""

        excerpt = self.extractor.extract_excerpt(pdf_path) or ""
        title = self._infer_title(pdf_path, excerpt)
        doi = canonical_doi(self._extract_doi(excerpt))
        paper = PaperMetadata(
            query_key=self.config.query_key,
            title=title,
            abstract=excerpt[:1600],
            source=source,
            doi=doi or None,
            pdf_link=source_url,
            pdf_path=str(pdf_path),
            open_access=True,
            external_ids={"doi": doi or "", "manual_pdf": str(pdf_path)},
            raw_payload={
                "manual_entry_kind": "local_pdf" if source_url is None else "manual_pdf_url",
                "manual_entry_url": source_url or "",
                "full_text_excerpt": excerpt,
            },
        )
        if not doi:
            return paper
        try:
            enriched = self._paper_from_doi(doi)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not enrich local PDF metadata via DOI %s: %s", doi, exc)
            return paper
        return enriched.merge_with(paper)

    def _attach_manual_url_metadata(self, paper: PaperMetadata, link: str) -> PaperMetadata:
        """Attach the originating user-supplied URL to a paper payload."""

        external_ids = {**paper.external_ids, "manual_url": link}
        raw_payload = {"manual_entry_url": link, **paper.raw_payload}
        return paper.model_copy(update={"external_ids": external_ids, "raw_payload": raw_payload})

    def _download_pdf(self, link: str, *, preferred_stem: str | None = None) -> Path:
        """Download one PDF into the configured paper directory and return the local file path."""

        target_dir = self.config.papers_dir / "manual_added"
        target_dir.mkdir(parents=True, exist_ok=True)
        stem_source = preferred_stem or Path(urlparse(link).path).stem or "manual-paper"
        safe_stem = normalize_title(stem_source).replace(" ", "-") or "manual-paper"
        target_path = target_dir / f"{safe_stem[:80]}.pdf"
        counter = 1
        while target_path.exists():
            target_path = target_dir / f"{safe_stem[:70]}-{counter}.pdf"
            counter += 1
        response = self.session.get(link, timeout=self.config.request_timeout_seconds, stream=True)
        response.raise_for_status()
        self._ensure_pdf_response(response, link)
        with target_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return target_path

    def _ensure_pdf_response(self, response: Response, link: str) -> None:
        """Reject non-PDF responses before they are written to disk."""

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "pdf" in content_type or link.lower().endswith(".pdf"):
            return
        raise ValueError(f"The URL did not return a PDF document: {link}")

    def _extract_html_title(self, payload: str) -> str:
        """Extract a document title from a simple HTML page response."""

        for meta_name in ("citation_title", "dc.title", "og:title"):
            meta_value = self._extract_meta_content(payload, meta_name)
            if meta_value:
                return meta_value
        match = self.TITLE_PATTERN.search(payload)
        return self._clean_html_text(match.group("title")) if match else ""

    def _extract_meta_content(self, payload: str, name: str) -> str:
        """Return one HTML meta content value when the requested tag is present."""

        normalized = name.lower()
        for match in self.META_PATTERN.finditer(payload):
            if match.group("name").lower() == normalized:
                return self._clean_html_text(match.group("content"))
        return ""

    def _extract_doi(self, text: str) -> str:
        """Find the first DOI-shaped token in arbitrary text or HTML."""

        match = self.DOI_PATTERN.search(text or "")
        return match.group(0) if match else ""

    def _extract_arxiv_identifier(self, value: str) -> str:
        """Extract an arXiv identifier from a page URL, PDF URL, or plain identifier string."""

        match = self.ARXIV_PATTERN.search(value or "")
        return match.group("identifier") if match else ""

    def _extract_pdf_link(self, payload: str, *, base_url: str) -> str | None:
        """Find a likely PDF link on a landing page."""

        for meta_name in ("citation_pdf_url", "og:pdf"):
            candidate = self._extract_meta_content(payload, meta_name)
            if candidate:
                return urljoin(base_url, candidate)
        for match in self.HREF_PATTERN.finditer(payload):
            href = match.group("href")
            if ".pdf" in href.lower():
                return urljoin(base_url, href)
        return None

    def _infer_title(self, pdf_path: Path, excerpt: str) -> str:
        """Infer a readable title from PDF text or the local filename."""

        for line in excerpt.splitlines():
            cleaned = " ".join(line.split()).strip()
            if len(cleaned) >= 20:
                return cleaned[:240]
        return pdf_path.stem.replace("_", " ").replace("-", " ").strip() or "Manual PDF"

    def _looks_like_pdf_link(self, link: str) -> bool:
        """Check whether a manual link likely targets a PDF directly."""

        lowered = link.lower()
        return lowered.endswith(".pdf") or "/pdf/" in lowered or "download=true" in lowered

    def _clean_html_text(self, value: str) -> str:
        """Normalize lightweight HTML text snippets into plain text."""

        cleaned = re.sub(r"<[^>]+>", " ", value or "")
        return " ".join(html.unescape(cleaned).split()).strip()
