"""Europe PMC discovery adapter for biomedical and life-science literature."""

from __future__ import annotations

from typing import Any

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import safe_year


class EuropePMCClient:
    """Search Europe PMC and normalize records into the shared paper model."""

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.europe_pmc_calls_per_second)

    def search(self) -> list[PaperMetadata]:
        """Search Europe PMC across the configured query variants and page windows."""

        papers: list[PaperMetadata] = []
        rows = self.config.results_per_page
        for query in self.config.discovery_queries:
            year_filtered_query = (
                f"({query}) AND FIRST_PDATE:[{self.config.year_range_start} TO {self.config.year_range_end}]"
            )
            for page in range(1, self.config.pages_to_retrieve + 1):
                payload = request_json(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=self.config.request_timeout_seconds,
                    params={
                        "query": year_filtered_query,
                        "format": "json",
                        "pageSize": rows,
                        "page": page,
                        "resultType": "core",
                    },
                )
                if not payload:
                    break
                items = ((payload.get("resultList") or {}).get("result") or [])
                papers.extend(self._parse_item(item) for item in items if item.get("title"))
                if len(papers) >= self.config.per_source_limit or len(items) < rows:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _parse_item(self, payload: dict[str, Any]) -> PaperMetadata:
        """Convert one Europe PMC search record into the shared paper representation."""

        author_entries = (payload.get("authorList") or {}).get("author") or []
        if isinstance(author_entries, dict):
            author_entries = [author_entries]
        authors = [
            author.get("fullName", "").strip()
            for author in author_entries
            if author.get("fullName")
        ]
        if not authors and payload.get("authorString"):
            authors = [name.strip() for name in str(payload["authorString"]).split(",") if name.strip()]
        full_text_links = (payload.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        if isinstance(full_text_links, dict):
            full_text_links = [full_text_links]
        pdf_link = next((link.get("url") for link in full_text_links if link.get("url")), None)
        journal = ((payload.get("journalInfo") or {}).get("journal") or {})
        doi = payload.get("doi")
        pmid = payload.get("pmid") or payload.get("id")
        return PaperMetadata(
            query_key=self.config.query_key,
            title=payload.get("title", ""),
            authors=authors,
            abstract=payload.get("abstractText", "") or "",
            year=safe_year(payload.get("pubYear")),
            venue=journal.get("title", ""),
            doi=doi,
            source="europe_pmc",
            citation_count=int(payload.get("citedByCount", 0) or 0),
            reference_count=0,
            pdf_link=pdf_link,
            open_access=bool(payload.get("isOpenAccess")) or bool(payload.get("hasPDF")),
            external_ids={
                "doi": doi or "",
                "pubmed": pmid or "",
                "source_id": payload.get("id", "") or "",
            },
            raw_payload=payload,
        )
