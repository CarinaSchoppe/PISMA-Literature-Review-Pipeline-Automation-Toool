from __future__ import annotations

import xml.etree.ElementTree as ET

from models.paper import PaperMetadata

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_text
from utils.text_processing import normalize_text, safe_year

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivClient:
    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session(
            "PRISMA-Literature-Review/1.0",
            extra_headers={"Accept": "application/atom+xml"},
        )
        self.limiter = RateLimiter(calls_per_second=0.34)

    def search(self) -> list[PaperMetadata]:
        papers: list[PaperMetadata] = []
        rows = self.config.results_per_page
        for query in self.config.discovery_queries:
            search_query = self._build_search_query(query)
            for page in range(self.config.pages_to_retrieve):
                start = page * rows
                payload = request_text(
                    self.session,
                    "GET",
                    self.BASE_URL,
                    limiter=self.limiter,
                    timeout=max(60, self.config.request_timeout_seconds),
                    params={
                        "search_query": search_query,
                        "start": start,
                        "max_results": rows,
                        "sortBy": "relevance",
                        "sortOrder": "descending",
                    },
                )
                if not payload:
                    break
                entries = self._parse_feed(payload)
                if not entries:
                    break
                filtered = [
                    paper
                    for paper in entries
                    if paper.year is None or self.config.year_range_start <= paper.year <= self.config.year_range_end
                ]
                papers.extend(filtered)
                if len(papers) >= self.config.per_source_limit or len(entries) < rows:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _build_search_query(self, query: str) -> str:
        terms = [query]
        operator = (self.config.boolean_operators or "AND").strip().upper()
        if operator not in {"AND", "OR", "NOT"}:
            return f'all:"{query}"'
        query_terms = []
        for term in terms:
            cleaned = normalize_text(term)
            if not cleaned:
                continue
            query_terms.append(f'all:"{cleaned}"')
        return f" {operator} ".join(query_terms) if query_terms else f'all:"{query}"'

    def _parse_feed(self, payload: str) -> list[PaperMetadata]:
        root = ET.fromstring(payload)
        papers: list[PaperMetadata] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            parsed = self._parse_entry(entry)
            if parsed:
                papers.append(parsed)
        return papers

    def _parse_entry(self, entry: ET.Element) -> PaperMetadata | None:
        title = normalize_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
        if not title:
            return None

        authors = [
            normalize_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
            if normalize_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        ]
        summary = normalize_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
        published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
        year = safe_year(published[:4])
        doi = normalize_text(entry.findtext("arxiv:doi", default="", namespaces=ATOM_NS)) or None

        pdf_link = None
        for link in entry.findall("atom:link", ATOM_NS):
            href = link.attrib.get("href", "").strip()
            title_hint = link.attrib.get("title", "").lower()
            if href and (title_hint == "pdf" or href.endswith(".pdf")):
                pdf_link = href
                break

        entry_id = normalize_text(entry.findtext("atom:id", default="", namespaces=ATOM_NS))
        primary_category = entry.find("arxiv:primary_category", ATOM_NS)
        category_term = primary_category.attrib.get("term", "") if primary_category is not None else ""
        return PaperMetadata(
            query_key=self.config.query_key,
            title=title,
            authors=authors,
            abstract=summary,
            year=year,
            venue="arXiv",
            doi=doi,
            source="arxiv",
            citation_count=0,
            reference_count=0,
            pdf_link=pdf_link,
            open_access=True,
            external_ids={
                "arxiv": entry_id.rsplit("/", 1)[-1] if entry_id else "",
                "doi": doi or "",
                "category": category_term,
            },
            raw_payload={
                "entry_id": entry_id,
                "published": published,
                "primary_category": category_term,
            },
        )
