"""Pydantic models for paper metadata and screening outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.text_processing import canonical_doi, normalize_title

DecisionLabel = Literal["include", "maybe", "exclude"]


class ScreeningResult(BaseModel):
    """Structured outcome returned by the heuristic or LLM-assisted screening step."""

    stage_one_decision: DecisionLabel = "maybe"
    relevance_score: float = 0.0
    topic_prefilter_score: float | None = None
    topic_prefilter_similarity: float | None = None
    topic_prefilter_model: str | None = None
    topic_prefilter_threshold: float | None = None
    topic_prefilter_label: str | None = None
    topic_prefilter_keyword_overlap: float | None = None
    topic_prefilter_research_fit_label: str | None = None
    topic_prefilter_weighted_score: float | None = None
    topic_prefilter_min_keyword_matches: int | None = None
    topic_prefilter_matched_keyword_count: int | None = None
    topic_prefilter_keyword_rule_count: int | None = None
    topic_prefilter_extracted_topics: list[str] = Field(default_factory=list)
    topic_prefilter_keyword_details: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    extracted_passage: str = ""
    methodology_category: str = "unspecified"
    domain_category: str = "unspecified"
    decision: DecisionLabel = "maybe"
    evaluation_breakdown: dict[str, float] = Field(default_factory=dict)
    matched_inclusion_criteria: list[str] = Field(default_factory=list)
    matched_exclusion_criteria: list[str] = Field(default_factory=list)
    matched_banned_topics: list[str] = Field(default_factory=list)
    matched_excluded_title_terms: list[str] = Field(default_factory=list)
    retain_reason: str = ""
    exclusion_reason: str = ""
    screening_context_key: str | None = None


class PaperMetadata(BaseModel):
    """Canonical representation of one literature record across all pipeline stages."""

    model_config = ConfigDict(populate_by_name=True)

    database_id: int | None = None
    query_key: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    source: str = ""
    citation_count: int = 0
    reference_count: int = 0
    pdf_link: str | None = None
    pdf_path: str | None = None
    open_access: bool = False
    relevance_score: float | None = None
    relevance_explanation: str | None = None
    inclusion_decision: str | None = None
    references: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    extracted_passage: str | None = None
    methodology_category: str | None = None
    domain_category: str | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    screening_details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Reject empty titles and normalize internal whitespace."""

        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            raise ValueError("Paper title cannot be empty")
        return cleaned

    @field_validator("authors", mode="before")
    @classmethod
    def validate_authors(cls, value: Any) -> list[str]:
        """Accept author lists or semicolon-separated author strings."""

        if not value:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(";") if part.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("abstract", "venue", mode="before")
    @classmethod
    def validate_text_fields(cls, value: Any) -> str:
        """Normalize abstract and venue fields to compact single-line text."""

        return " ".join(str(value or "").split()).strip()

    @field_validator("doi", mode="before")
    @classmethod
    def validate_doi(cls, value: Any) -> str | None:
        """Canonicalize DOI values and collapse empty values to None."""

        normalized = canonical_doi(str(value or ""))
        return normalized or None

    @property
    def normalized_title(self) -> str:
        """Return a title string normalized for deduplication and indexing."""

        return normalize_title(self.title)

    @property
    def identity_key(self) -> str:
        """Return the preferred identity key used across deduplication and caching."""

        if self.doi:
            return f"doi:{self.doi}"
        return f"title:{self.normalized_title}"

    @property
    def citation_label(self) -> str:
        """Return a concise label for citation expansion logs and displays."""

        return self.doi or self.title

    def merge_with(self, other: "PaperMetadata") -> "PaperMetadata":
        """Combine metadata from two records that refer to the same underlying paper."""

        merged_authors = list(dict.fromkeys([*self.authors, *other.authors]))
        merged_references = list(dict.fromkeys([*self.references, *other.references]))
        merged_citations = list(dict.fromkeys([*self.citations, *other.citations]))
        merged_external_ids = {**self.external_ids, **other.external_ids}
        merged_payload = {**self.raw_payload, **other.raw_payload}
        return self.model_copy(
            update={
                "authors": merged_authors,
                "abstract": self.abstract if len(self.abstract) >= len(other.abstract) else other.abstract,
                "year": self.year or other.year,
                "venue": self.venue or other.venue,
                "doi": self.doi or other.doi,
                "source": ", ".join(sorted(set(filter(None, [self.source, other.source])))),
                "citation_count": max(self.citation_count, other.citation_count),
                "reference_count": max(self.reference_count, other.reference_count),
                "pdf_link": self.pdf_link or other.pdf_link,
                "pdf_path": self.pdf_path or other.pdf_path,
                "open_access": self.open_access or other.open_access,
                "references": merged_references,
                "citations": merged_citations,
                "external_ids": merged_external_ids,
                "raw_payload": merged_payload,
                "screening_details": self.screening_details or other.screening_details,
            }
        )

