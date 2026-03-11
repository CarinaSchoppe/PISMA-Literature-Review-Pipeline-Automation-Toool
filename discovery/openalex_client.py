"""OpenAlex discovery and citation lookups for scholarly works metadata."""

from __future__ import annotations

from typing import Any

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import reconstruct_inverted_abstract


class OpenAlexClient:
    """Search OpenAlex and resolve references or citing papers for known works."""

    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.openalex_calls_per_second)

    def search(self) -> list[PaperMetadata]:
        """Search OpenAlex across configured query variants and pagination windows."""

        papers: list[PaperMetadata] = []
        for query in self.config.discovery_queries:
            for page in range(1, self.config.pages_to_retrieve + 1):
                params = {
                    "search": query,
                    "per-page": self.config.results_per_page,
                    "page": page,
                    "filter": (
                        f"from_publication_date:{self.config.year_range_start}-01-01,"
                        f"to_publication_date:{self.config.year_range_end}-12-31"
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
                items = payload.get("results", [])
                papers.extend(self._parse_work(item) for item in items if item.get("display_name"))
                if len(papers) >= self.config.per_source_limit or len(items) < self.config.results_per_page:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def fetch_work_by_id(self, work_id: str) -> PaperMetadata | None:
        """Fetch one OpenAlex work by its identifier."""

        normalized_id = work_id.rstrip("/").split("/")[-1]
        payload = request_json(
            self.session,
            "GET",
            f"{self.BASE_URL}/{normalized_id}",
            limiter=self.limiter,
            timeout=self.config.request_timeout_seconds,
            params={"mailto": self.config.api_settings.crossref_mailto}
            if self.config.api_settings.crossref_mailto
            else None,
        )
        if not payload or not payload.get("display_name"):
            return None
        return self._parse_work(payload)

    def resolve_work(self, paper: PaperMetadata) -> PaperMetadata | None:
        """Resolve a paper to the closest OpenAlex work for citation expansion."""

        openalex_id = paper.external_ids.get("openalex")
        if openalex_id:
            return self.fetch_work_by_id(openalex_id)
        search_terms = [paper.doi, paper.title]
        for term in search_terms:
            if not term:
                continue
            payload = request_json(
                self.session,
                "GET",
                self.BASE_URL,
                limiter=self.limiter,
                timeout=self.config.request_timeout_seconds,
                params={"search": term, "per-page": 5},
            )
            if not payload:
                continue
            for item in payload.get("results", []):
                candidate = self._parse_work(item)
                if paper.doi and candidate.doi == paper.doi:
                    return candidate
                if candidate.normalized_title == paper.normalized_title:
                    return candidate
        return None

    def fetch_references(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Fetch referenced works for a resolved OpenAlex record."""

        resolved = self.resolve_work(paper)
        if not resolved:
            return []
        references = []
        for work_id in resolved.references[:limit]:
            reference = self.fetch_work_by_id(work_id)
            if reference:
                references.append(reference)
        return references

    def fetch_citations(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Fetch works that cite the resolved OpenAlex paper."""

        resolved = self.resolve_work(paper)
        openalex_id = resolved.external_ids.get("openalex") if resolved else None
        if not openalex_id:
            return []
        normalized_id = openalex_id.rstrip("/").split("/")[-1]
        payload = request_json(
            self.session,
            "GET",
            self.BASE_URL,
            limiter=self.limiter,
            timeout=self.config.request_timeout_seconds,
            params={
                "filter": f"cites:{normalized_id}",
                "per-page": min(limit, 50),
                "page": 1,
            },
        )
        if not payload:
            return []
        return [self._parse_work(item) for item in payload.get("results", [])[:limit] if item.get("display_name")]

    def _parse_work(self, payload: dict[str, Any]) -> PaperMetadata:
        """Convert an OpenAlex work payload into the shared paper model."""

        authors = [
            authorship.get("author", {}).get("display_name", "").strip()
            for authorship in payload.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        open_access_info = payload.get("open_access", {}) or {}
        best_oa_location = payload.get("best_oa_location", {}) or {}
        primary_location = payload.get("primary_location") or {}
        source_info = primary_location.get("source") or {}
        ids = payload.get("ids", {}) or {}
        doi = ids.get("doi") or payload.get("doi")
        references = payload.get("referenced_works", []) or []
        return PaperMetadata(
            query_key=self.config.query_key,
            title=payload.get("display_name", ""),
            authors=authors,
            abstract=reconstruct_inverted_abstract(payload.get("abstract_inverted_index")),
            year=payload.get("publication_year"),
            venue=source_info.get("display_name", ""),
            doi=doi,
            source="openalex",
            citation_count=payload.get("cited_by_count", 0) or 0,
            reference_count=len(references),
            pdf_link=best_oa_location.get("pdf_url") or open_access_info.get("oa_url"),
            open_access=bool(open_access_info.get("is_oa")),
            references=references,
            external_ids={
                "openalex": payload.get("id", ""),
                **{key.lower(): str(value) for key, value in ids.items() if value},
            },
            raw_payload=payload,
        )
