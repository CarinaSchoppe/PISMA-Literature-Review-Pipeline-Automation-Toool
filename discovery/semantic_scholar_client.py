from __future__ import annotations

from typing import Any

from models.paper import PaperMetadata

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_json


class SemanticScholarClient:
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
        self.limiter = RateLimiter(calls_per_second=3.0)

    def search(self) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        limit = self.config.results_per_page
        for query in self.config.discovery_queries:
            for page in range(self.config.pages_to_retrieve):
                offset = page * limit
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    params={
                        "query": query,
                        "limit": limit,
                        "offset": offset,
                        "fields": self.SEARCH_FIELDS,
                        "year": f"{self.config.year_range_start}-{self.config.year_range_end}",
                    },
                )
                if not payload:
                    break
                items = payload.get("data", [])
                papers.extend(self._parse_paper(item) for item in items if item.get("title"))
                if len(papers) >= self.config.per_source_limit or len(items) < limit:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_paper(self, payload: dict[str, Any]) -> PaperMetadata:
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
