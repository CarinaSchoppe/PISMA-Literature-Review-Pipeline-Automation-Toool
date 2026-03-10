from __future__ import annotations

from typing import Any

from models.paper import PaperMetadata

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import safe_year, strip_markup


class CrossrefClient:
    BASE_URL = "https://api.crossref.org/works"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=2.5)

    def search(self) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        rows = self.config.results_per_page
        for query in self.config.discovery_queries:
            for page in range(self.config.pages_to_retrieve):
                offset = page * rows
                params = {
                    "query.bibliographic": query,
                    "rows": rows,
                    "offset": offset,
                    "filter": (
                        f"from-pub-date:{self.config.year_range_start}-01-01,"
                        f"until-pub-date:{self.config.year_range_end}-12-31"
                    ),
                }
                if self.config.api_settings.crossref_mailto:
                    params["mailto"] = self.config.api_settings.crossref_mailto
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    params=params,
                )
                if not payload:
                    break
                items = (payload.get("message") or {}).get("items", [])
                papers.extend(self._parse_item(item) for item in items if item.get("title"))
                if len(papers) >= self.config.per_source_limit or len(items) < rows:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_item(self, payload: dict[str, Any]) -> PaperMetadata:
        authors = []
        for author in payload.get("author", []) or []:
            parts = [author.get("given", ""), author.get("family", "")]
            name = " ".join(part.strip() for part in parts if part).strip()
            if name:
                authors.append(name)

        date_parts = payload.get("published-print", {}).get("date-parts") or payload.get("published-online", {}).get("date-parts") or []
        year = safe_year(date_parts[0][0] if date_parts and date_parts[0] else payload.get("published"))

        pdf_link = None
        for link in payload.get("link", []) or []:
            if link.get("content-type") == "application/pdf":
                pdf_link = link.get("URL")
                break

        references = payload.get("reference", []) or []
        return PaperMetadata(
            query_key=self.config.query_key,
            title=(payload.get("title") or [""])[0],
            authors=authors,
            abstract=strip_markup(payload.get("abstract", "") or ""),
            year=year,
            venue=(payload.get("container-title") or [""])[0],
            doi=payload.get("DOI"),
            source="crossref",
            citation_count=payload.get("is-referenced-by-count", 0) or 0,
            reference_count=len(references),
            pdf_link=pdf_link,
            open_access=bool(pdf_link),
            references=[
                reference.get("DOI") or reference.get("article-title") or reference.get("unstructured", "")
                for reference in references
                if reference
            ],
            external_ids={"doi": payload.get("DOI", "")},
            raw_payload=payload,
        )
