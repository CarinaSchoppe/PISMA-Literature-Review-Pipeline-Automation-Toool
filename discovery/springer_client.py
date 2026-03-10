from __future__ import annotations

import logging
from typing import Any

from models.paper import PaperMetadata

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import safe_year, strip_markup

LOGGER = logging.getLogger(__name__)


class SpringerClient:
    BASE_URL = "https://api.springernature.com/meta/v2/json"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=1.0)

    def search(self) -> list[PaperMetadata]:
        api_key = self.config.api_settings.springer_api_key
        if not api_key:
            LOGGER.warning("Springer discovery was enabled but SPRINGER_API_KEY is not configured.")
            return []

        papers: list[PaperMetadata] = []
        rows = self.config.results_per_page
        for query in self.config.discovery_queries:
            for page in range(self.config.pages_to_retrieve):
                start = page * rows + 1
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    params={
                        "q": query,
                        "p": rows,
                        "s": start,
                        "api_key": api_key,
                    },
                )
                if not payload:
                    break
                items = payload.get("records", []) or []
                parsed = [self._parse_record(item) for item in items if item.get("title")]
                papers.extend(
                    paper
                    for paper in parsed
                    if paper.year is None or self.config.year_range_start <= paper.year <= self.config.year_range_end
                )
                if len(papers) >= self.config.per_source_limit or len(items) < rows:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_record(self, payload: dict[str, Any]) -> PaperMetadata:
        creators = payload.get("creators") or []
        authors: list[str] = []
        for creator in creators:
            if isinstance(creator, dict):
                name = str(creator.get("creator", "")).strip()
            else:
                name = str(creator).strip()
            if name:
                authors.append(name)

        urls = payload.get("url") or []
        pdf_link = None
        for url_info in urls:
            value = str((url_info or {}).get("value", "")).strip()
            format_hint = str((url_info or {}).get("format", "")).lower()
            if value and ("pdf" in format_hint or value.lower().endswith(".pdf")):
                pdf_link = value
                break

        doi = payload.get("doi") or payload.get("identifier")
        year = safe_year(str(payload.get("publicationDate", ""))[:4])
        open_access_value = str(payload.get("openaccess", "")).strip().lower()
        open_access = open_access_value in {"true", "1", "yes"} or bool(pdf_link)

        return PaperMetadata(
            query_key=self.config.query_key,
            title=str(payload.get("title", "")).strip(),
            authors=authors,
            abstract=strip_markup(str(payload.get("abstract", "") or "")),
            year=year,
            venue=str(payload.get("publicationName", "") or payload.get("publicationTitle", "") or "").strip(),
            doi=doi,
            source="springer",
            citation_count=0,
            reference_count=0,
            pdf_link=pdf_link,
            open_access=open_access,
            external_ids={
                "doi": str(doi or ""),
                "springer_identifier": str(payload.get("identifier", "") or ""),
            },
            raw_payload=payload,
        )
