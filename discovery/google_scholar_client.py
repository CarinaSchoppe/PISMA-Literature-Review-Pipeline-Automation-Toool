"""Google Scholar HTML discovery client with bounded page traversal and resilient parsing."""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Callable
from urllib.parse import urljoin

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_text
from utils.text_processing import canonical_doi, strip_markup

LOGGER = logging.getLogger(__name__)

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
RESULT_SPLIT_PATTERN = re.compile(r'(?=<div[^>]+class="[^"]*gs_r[^"]*gs_or[^"]*")', re.IGNORECASE)
TITLE_LINK_PATTERN = re.compile(r'<h3[^>]*class="[^"]*gs_rt[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TITLE_TEXT_PATTERN = re.compile(r'<h3[^>]*class="[^"]*gs_rt[^"]*"[^>]*>(.*?)</h3>', re.IGNORECASE | re.DOTALL)
META_PATTERN = re.compile(r'<div[^>]*class="[^"]*gs_a[^"]*"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)
SNIPPET_PATTERN = re.compile(r'<div[^>]*class="[^"]*gs_rs[^"]*"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)
PDF_LINK_PATTERN = re.compile(r'<div[^>]*class="[^"]*gs_or_ggsm[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"', re.IGNORECASE | re.DOTALL)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


class GoogleScholarClient:
    """Retrieve Google Scholar result pages and normalize them into shared paper metadata."""

    BASE_URL = "https://scholar.google.com/scholar"

    def __init__(self, config: ResearchConfig, *, should_stop: Callable[[], bool] | None = None) -> None:
        self.config = config
        self.should_stop = should_stop or (lambda: False)
        self.session = build_session(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 PRISMA-Literature-Review/1.0",
            extra_headers={"Accept": "text/html,application/xhtml+xml"},
        )
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.google_scholar_calls_per_second)

    def search(self) -> list[PaperMetadata]:
        """Collect Scholar search results across the configured page window."""

        papers: list[PaperMetadata] = []
        results_per_page = max(int(self.config.google_scholar_results_per_page), 1)
        page_limit = max(int(self.config.google_scholar_pages), 1)
        source_limit = max(self.config.per_source_limit, page_limit * results_per_page)
        for query in self.config.discovery_queries:
            if self.should_stop():
                LOGGER.info("Google Scholar discovery stopped before query '%s' due to a user stop request.", query)
                break
            LOGGER.info("Google Scholar discovery starting for query '%s'.", query)
            for page_index in range(page_limit):
                if self.should_stop():
                    LOGGER.info(
                        "Google Scholar discovery stopped before page %s for query '%s' due to a user stop request.",
                        page_index + 1,
                        query,
                    )
                    return papers[:source_limit]
                if len(papers) >= source_limit:
                    return papers[:source_limit]
                start_index = page_index * results_per_page
                LOGGER.info(
                    "Google Scholar fetching page %s/%s for query '%s' (start=%s, limit=%s).",
                    page_index + 1,
                    page_limit,
                    query,
                    start_index,
                    results_per_page,
                )
                html = request_text(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    use_cache=True,
                    params={
                        "q": query,
                        "hl": "en",
                        "start": start_index,
                        "num": results_per_page,
                        "as_ylo": self.config.year_range_start,
                        "as_yhi": self.config.year_range_end,
                    },
                )
                if not html:
                    LOGGER.warning("Google Scholar page %s returned no content for query '%s'.", page_index + 1, query)
                    continue
                page_results = self._parse_page(html)
                LOGGER.info(
                    "Google Scholar page %s produced %s parsed results.",
                    page_index + 1,
                    len(page_results),
                )
                papers.extend(page_results)
                if len(page_results) < results_per_page:
                    break
        return papers[:source_limit]

    def _parse_page(self, html: str) -> list[PaperMetadata]:
        """Extract result cards from one Scholar HTML page."""

        papers: list[PaperMetadata] = []
        blocks = [segment for segment in RESULT_SPLIT_PATTERN.split(html) if "gs_rt" in segment]
        for block_index, block in enumerate(blocks, start=1):
            paper = self._parse_result_block(block)
            if paper is None:
                continue
            if self.config.verbosity == "ultra_verbose":
                LOGGER.debug(
                    "Google Scholar parsed result %s: title='%s', year=%s, doi=%s, pdf=%s.",
                    block_index,
                    paper.title,
                    paper.year,
                    paper.doi or "(missing)",
                    paper.pdf_link or "(missing)",
                )
            papers.append(paper)
        return papers

    def _parse_result_block(self, block: str) -> PaperMetadata | None:
        """Convert one Scholar result card into the shared paper model."""

        title, result_url = self._extract_title_and_url(block)
        if not title:
            return None
        meta_text = self._extract_block_text(META_PATTERN, block)
        snippet = self._extract_block_text(SNIPPET_PATTERN, block)
        pdf_url = self._extract_url(PDF_LINK_PATTERN, block)
        raw_doi = self._extract_doi(block) or self._extract_doi(snippet)
        doi = canonical_doi(raw_doi) or None
        authors, venue, year = self._parse_meta(meta_text)
        if self.config.verbosity == "ultra_verbose":
            LOGGER.debug(
                "Google Scholar metadata extracted for '%s': authors=%s venue=%s year=%s doi=%s.",
                title,
                len(authors),
                venue or "(missing)",
                year,
                doi or "(missing)",
            )
        return PaperMetadata(
            query_key=self.config.query_key,
            title=title,
            authors=authors,
            abstract=snippet,
            year=year,
            venue=venue,
            doi=doi,
            source="google_scholar",
            citation_count=0,
            reference_count=0,
            pdf_link=pdf_url,
            open_access=bool(pdf_url),
            raw_payload={
                "result_url": result_url,
                "pdf_url": pdf_url,
                "meta": meta_text,
                "snippet": snippet,
                "doi": doi,
            },
        )

    def _extract_title_and_url(self, block: str) -> tuple[str, str | None]:
        """Extract the visible result title and landing URL from one Scholar card."""

        linked_match = TITLE_LINK_PATTERN.search(block)
        if linked_match:
            return self._clean_html_text(linked_match.group(2)), unescape(linked_match.group(1))
        plain_match = TITLE_TEXT_PATTERN.search(block)
        if plain_match:
            return self._clean_html_text(plain_match.group(1)), None
        return "", None

    def _extract_block_text(self, pattern: re.Pattern[str], block: str) -> str:
        """Return the cleaned text for a matched metadata or snippet block."""

        match = pattern.search(block)
        if not match:
            return ""
        return self._clean_html_text(match.group(1))

    def _extract_url(self, pattern: re.Pattern[str], block: str) -> str | None:
        """Extract and normalize a linked URL from a result sub-block."""

        match = pattern.search(block)
        if not match:
            return None
        return urljoin(self.BASE_URL, unescape(match.group(1)))

    def _extract_doi(self, block: str) -> str:
        """Look for a DOI anywhere inside the result card."""

        match = DOI_PATTERN.search(block)
        return match.group(0) if match else ""

    def _parse_meta(self, meta_text: str) -> tuple[list[str], str, int | None]:
        """Extract authors, venue, and year from the Scholar metadata line."""

        if not meta_text:
            return [], "", None
        year_match = YEAR_PATTERN.search(meta_text)
        year = int(year_match.group(0)) if year_match else None
        parts = [part.strip() for part in meta_text.split(" - ") if part.strip()]
        authors = [part.strip() for part in parts[0].split(",") if part.strip()] if parts else []
        venue = ""
        if len(parts) >= 2:
            venue = parts[1]
        return authors, venue, year

    def _clean_html_text(self, value: str) -> str:
        """Collapse HTML fragments into plain display text."""

        return " ".join(strip_markup(unescape(value)).split())






