"""PubMed discovery client built on the NCBI E-utilities API."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.http import RateLimiter, build_session, request_json
from utils.text_processing import chunked, normalize_text, safe_year


class PubMedClient:
    """Search PubMed for biomedical queries and normalize fetched XML records."""

    SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.session = build_session("PRISMA-Literature-Review/1.0")
        self.limiter = RateLimiter(calls_per_second=self.config.api_settings.pubmed_calls_per_second)

    def search(self) -> list[PaperMetadata]:
        """Search PubMed when the run configuration enables the biomedical source."""

        if not self.config.include_pubmed:
            return []
        papers: list[PaperMetadata] = []
        seen_pmids: set[str] = set()
        for query in self.config.discovery_queries:
            search_term = (
                f"({query}) AND "
                f"({self.config.year_range_start}:{self.config.year_range_end}[pdat])"
            )
            payload = request_json(
                self.session,
                "GET",
                self.SEARCH_URL,
                limiter=self.limiter,
                timeout=self.config.request_timeout_seconds,
                params={
                    "db": "pubmed",
                    "retmode": "json",
                    "retmax": self.config.per_source_limit,
                    "term": search_term,
                },
            )
            if not payload:
                continue
            pmids = [
                pmid
                for pmid in payload.get("esearchresult", {}).get("idlist", [])
                if pmid not in seen_pmids
            ]
            seen_pmids.update(pmids)
            for batch in chunked(pmids, 100):
                papers.extend(self._fetch_batch(batch))
                if len(papers) >= self.config.per_source_limit:
                    break
            if len(papers) >= self.config.per_source_limit:
                break
        return papers[: self.config.per_source_limit]

    def _fetch_batch(self, pmids: list[str]) -> list[PaperMetadata]:
        """Fetch a batch of PubMed XML records for a list of PMIDs."""

        self.limiter.wait()
        response = self.session.get(
            self.FETCH_URL,
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
            },
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        papers = []
        for article in root.findall(".//PubmedArticle"):
            parsed = self._parse_article(article)
            if parsed:
                papers.append(parsed)
        return papers

    def _parse_article(self, article: ET.Element) -> PaperMetadata | None:
        """Convert one PubMed XML article into the shared paper model."""

        citation = article.find("./MedlineCitation")
        if citation is None:
            return None
        article_info = citation.find("./Article")
        if article_info is None:
            return None
        title = normalize_text("".join(article_info.findtext("./ArticleTitle", default="")))
        if not title:
            return None

        abstract_parts = [
            normalize_text("".join(node.itertext()))
            for node in article_info.findall("./Abstract/AbstractText")
            if normalize_text("".join(node.itertext()))
        ]
        authors = []
        for author in article_info.findall("./AuthorList/Author"):
            fore = author.findtext("./ForeName", default="")
            last = author.findtext("./LastName", default="")
            collective = author.findtext("./CollectiveName", default="")
            name = normalize_text(" ".join(part for part in [fore, last] if part)) or normalize_text(collective)
            if name:
                authors.append(name)

        pub_date = article_info.find("./Journal/JournalIssue/PubDate")
        year = None
        if pub_date is not None:
            year = safe_year(
                pub_date.findtext("./Year", default="")
                or pub_date.findtext("./MedlineDate", default="")[:4]
            )
        article_ids = article.findall("./PubmedData/ArticleIdList/ArticleId")
        doi = None
        pmcid = None
        for article_id in article_ids:
            id_type = article_id.attrib.get("IdType", "").lower()
            if id_type == "doi":
                doi = article_id.text
            if id_type == "pmc":
                pmcid = article_id.text

        pmid = citation.findtext("./PMID", default="")
        return PaperMetadata(
            query_key=self.config.query_key,
            title=title,
            authors=authors,
            abstract=" ".join(abstract_parts),
            year=year,
            venue=article_info.findtext("./Journal/Title", default=""),
            doi=doi,
            source="pubmed",
            citation_count=0,
            reference_count=0,
            open_access=bool(pmcid),
            external_ids={
                "pubmed": pmid,
                "pmcid": pmcid or "",
                "doi": doi or "",
            },
            raw_payload={"pmid": pmid},
        )
