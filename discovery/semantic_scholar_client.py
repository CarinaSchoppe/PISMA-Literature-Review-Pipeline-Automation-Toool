"""Semantic Scholar discovery client used for metadata recall and ranking signals."""

from __future__ import annotations

import logging
from typing import Any

from models.paper import PaperMetadata

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_json

LOGGER = logging.getLogger(__name__)


class SemanticScholarClient:
    """Search Semantic Scholar and normalize the returned paper metadata."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    SEARCH_FIELDS = ",".join(
        [
            "paperId",
            "title",
            "abstract",
            "year",
            "venue",
            "authors",
            "citationCount",
            "referenceCount",
            "externalIds",
            "openAccessPdf",
            "url",
            "publicationDate",
        ]
    )

    def __init__(self, config: ResearchConfig) -> None:
        headers = {}
        if config.api_settings.semantic_scholar_api_key:
            headers["x-api-key"] = config.api_settings.semantic_scholar_api_key
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0", extra_headers=headers)
        self.limiter = RateLimiter(
            calls_per_second=self.config.api_settings.semantic_scholar_calls_per_second,
            max_requests_per_minute=self.config.api_settings.semantic_scholar_max_requests_per_minute,
            request_delay_seconds=self.config.api_settings.semantic_scholar_request_delay_seconds,
            name="Semantic Scholar",
        )

    def search(self) -> list[PaperMetadata]:
        """Search Semantic Scholar across configured query variants."""

        papers: list[PaperMetadata] = []
        limit = self.config.results_per_page
        for query in self.config.discovery_queries:
            LOGGER.info("Semantic Scholar discovery starting for query '%s'.", query)
            for page in range(self.config.pages_to_retrieve):
                offset = page * limit
                LOGGER.info(
                    "Semantic Scholar fetching page %s/%s for query '%s' (offset=%s, limit=%s).",
                    page + 1,
                    self.config.pages_to_retrieve,
                    query,
                    offset,
                    limit,
                )
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    retry_max_attempts=self.config.api_settings.semantic_scholar_retry_attempts,
                    retry_backoff_strategy=self.config.api_settings.semantic_scholar_retry_backoff_strategy,
                    retry_base_delay_seconds=self.config.api_settings.semantic_scholar_retry_backoff_base_seconds,
                    request_label="Semantic Scholar",
                    params={
                        "query": query,
                        "limit": limit,
                        "offset": offset,
                        "fields": self.SEARCH_FIELDS,
                        "year": f"{self.config.year_range_start}-{self.config.year_range_end}",
                    },
                )
                if not payload:
                    LOGGER.warning("Semantic Scholar page %s returned no payload for query '%s'.", page + 1, query)
                    break
                items = payload.get("data", [])
                page_results = [self._parse_paper(item) for item in items if item.get("title")]
                LOGGER.info("Semantic Scholar page %s produced %s parsed results.", page + 1, len(page_results))
                papers.extend(page_results)
                if len(papers) >= self.config.per_source_limit or len(items) < limit:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_paper(self, payload: dict[str, Any]) -> PaperMetadata:
        """Convert one Semantic Scholar result into the shared paper model."""

        external_ids = {str(key).lower(): str(value) for key, value in (payload.get("externalIds") or {}).items() if value}
        pdf_info = payload.get("openAccessPdf") or {}
        doi = external_ids.get("doi")
        return PaperMetadata(
            query_key=self.config.query_key,
            title=payload.get("title", ""),
            authors=[author.get("name", "").strip() for author in payload.get("authors", []) if author.get("name")],
            abstract=payload.get("abstract", "") or "",
            year=payload.get("year"),
            venue=payload.get("venue", "") or "",
            doi=doi,
            source="semantic_scholar",
            citation_count=payload.get("citationCount", 0) or 0,
            reference_count=payload.get("referenceCount", 0) or 0,
            pdf_link=pdf_info.get("url"),
            open_access=bool(pdf_info.get("url")),
            external_ids={
                "semantic_scholar": payload.get("paperId", ""),
                **external_ids,
            },
            raw_payload=payload,
        )
