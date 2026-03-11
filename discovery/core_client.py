"""CORE discovery adapter for open-access repository and preprint content."""

from __future__ import annotations

from typing import Any

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import safe_year


class COREClient:
    """Search the CORE API and normalize records into the shared paper model."""

    BASE_URL = "https://api.core.ac.uk/v3/search/works"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        if self.config.api_settings.core_api_key:
            self.session.headers["Authorization"] = f"Bearer {self.config.api_settings.core_api_key}"
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.core_calls_per_second)

    def search(self) -> list[PaperMetadata]:
        """Search CORE across the configured query variants and page windows."""

        papers: list[PaperMetadata] = []
        rows = self.config.results_per_page
        for query in self.config.discovery_queries:
            for page in range(self.config.pages_to_retrieve):
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    params={
                        "q": query,
                        "limit": rows,
                        "offset": page * rows,
                    },
                )
                if not payload:
                    break
                items = payload.get("results") or []
                filtered = []
                for item in items:
                    item_year = safe_year(item.get("yearPublished"))
                    if not item.get("title"):
                        continue
                    if item_year is not None and not (self.config.year_range_start <= item_year <= self.config.year_range_end):
                        continue
                    filtered.append(self._parse_item(item))
                papers.extend(filtered)
                if len(papers) >= self.config.per_source_limit or len(items) < rows:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_item(self, payload: dict[str, Any]) -> PaperMetadata:
        """Convert one CORE search record into the shared paper representation."""

        authors = [
            author.get("name", "").strip()
            for author in payload.get("authors", []) or []
            if author.get("name")
        ]
        journals = payload.get("journals") or []
        venue = journals[0].get("title", "") if journals else payload.get("publisher", "") or ""
        pdf_link = payload.get("downloadUrl") or next(iter(payload.get("sourceFulltextUrls") or []), None)
        doi = payload.get("doi")
        identifiers = payload.get("identifiers") or []
        external_ids = {
            "doi": doi or "",
            "core": str(payload.get("id", "") or ""),
            "arxiv": payload.get("arxivId", "") or "",
            "pubmed": str(payload.get("pubmedId", "") or ""),
        }
        for identifier in identifiers:
            id_type = str(identifier.get("type", "")).lower()
            id_value = str(identifier.get("identifier", "") or "")
            if id_type and id_value and id_type not in external_ids:
                external_ids[id_type] = id_value
        references = [str(reference) for reference in (payload.get("references") or []) if reference]
        return PaperMetadata(
            query_key=self.config.query_key,
            title=payload.get("title", ""),
            authors=authors,
            abstract=payload.get("abstract", "") or "",
            year=safe_year(payload.get("yearPublished")),
            venue=venue,
            doi=doi,
            source="core",
            citation_count=int(payload.get("citationCount", 0) or 0),
            reference_count=len(references),
            pdf_link=pdf_link,
            open_access=bool(pdf_link),
            references=references,
            external_ids=external_ids,
            raw_payload=payload,
        )
