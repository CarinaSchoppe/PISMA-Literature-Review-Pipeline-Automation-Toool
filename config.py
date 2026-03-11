"""Configuration models and CLI parsing for the literature review pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator, model_validator

from utils.logging_utils import build_log_file_path, normalize_verbosity
from utils.text_processing import build_query, ensure_parent_directory, make_query_key, parse_search_terms

BIOMEDICAL_TERMS = {
    "biomedical",
    "medicine",
    "medical",
    "clinical",
    "drug",
    "patient",
    "therapy",
    "health",
    "diagnosis",
    "pubmed",
    "epidemiology",
    "oncology",
    "genomics",
}

SCREENING_ALGORITHM_VERSION = "2026-03-10-v3"
DEFAULT_EXCLUDED_TITLE_TERMS = [
    "correction",
    "erratum",
    "editorial",
    "retraction",
]
DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN = 1
DEFAULT_GOOGLE_SCHOLAR_PAGE_MAX = 100


class ApiSettings(BaseModel):
    """API credentials, endpoints, and model settings resolved from env vars or config."""

    semantic_scholar_api_key: str | None = Field(default_factory=lambda: os.getenv("SEMANTIC_SCHOLAR_API_KEY"))
    crossref_mailto: str | None = Field(default_factory=lambda: os.getenv("CROSSREF_MAILTO"))
    unpaywall_email: str | None = Field(default_factory=lambda: os.getenv("UNPAYWALL_EMAIL"))
    springer_api_key: str | None = Field(default_factory=lambda: os.getenv("SPRINGER_API_KEY"))
    core_api_key: str | None = Field(default_factory=lambda: os.getenv("CORE_API_KEY"))
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.4"))
    gemini_api_key: str | None = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    gemini_base_url: str = Field(
        default_factory=lambda: os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    )
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    ollama_base_url: str = Field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    ollama_model: str = Field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3:8b"))
    ollama_api_key: str = Field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", "ollama"))
    huggingface_model: str = Field(default_factory=lambda: os.getenv("HF_MODEL_ID", "Qwen/Qwen3-14B"))
    huggingface_task: str = Field(default_factory=lambda: os.getenv("HF_TASK", "text-generation"))
    huggingface_device: str = Field(default_factory=lambda: os.getenv("HF_DEVICE", "auto"))
    huggingface_dtype: str = Field(default_factory=lambda: os.getenv("HF_DTYPE", "auto"))
    huggingface_max_new_tokens: int = Field(default_factory=lambda: int(os.getenv("HF_MAX_NEW_TOKENS", "700")))
    huggingface_cache_dir: str | None = Field(default_factory=lambda: os.getenv("HF_HOME") or os.getenv("TRANSFORMERS_CACHE"))
    huggingface_trust_remote_code: bool = Field(
        default_factory=lambda: os.getenv("HF_TRUST_REMOTE_CODE", "false").strip().lower() in {"1", "true", "yes", "y"}
    )
    llm_temperature: float = Field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1")))
    openalex_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("OPENALEX_CALLS_PER_SECOND", "5.0")))
    semantic_scholar_calls_per_second: float = Field(
        default_factory=lambda: float(os.getenv("SEMANTIC_SCHOLAR_CALLS_PER_SECOND", "3.0"))
    )
    crossref_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("CROSSREF_CALLS_PER_SECOND", "2.5")))
    springer_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("SPRINGER_CALLS_PER_SECOND", "1.0")))
    arxiv_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("ARXIV_CALLS_PER_SECOND", "0.34")))
    pubmed_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("PUBMED_CALLS_PER_SECOND", "3.0")))
    europe_pmc_calls_per_second: float = Field(
        default_factory=lambda: float(os.getenv("EUROPE_PMC_CALLS_PER_SECOND", "2.0"))
    )
    core_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("CORE_CALLS_PER_SECOND", "1.5")))
    unpaywall_calls_per_second: float = Field(default_factory=lambda: float(os.getenv("UNPAYWALL_CALLS_PER_SECOND", "2.0")))
    topic_prefilter_model: str = Field(
        default_factory=lambda: os.getenv("HF_TOPIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    google_scholar_calls_per_second: float = Field(
        default_factory=lambda: float(os.getenv("GOOGLE_SCHOLAR_CALLS_PER_SECOND", "0.2"))
    )
    semantic_scholar_max_requests_per_minute: int = Field(
        default_factory=lambda: int(os.getenv("SEMANTIC_SCHOLAR_MAX_REQUESTS_PER_MINUTE", "120"))
    )
    semantic_scholar_request_delay_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SEMANTIC_SCHOLAR_REQUEST_DELAY_SECONDS", "0.0"))
    )
    semantic_scholar_retry_attempts: int = Field(
        default_factory=lambda: int(os.getenv("SEMANTIC_SCHOLAR_RETRY_ATTEMPTS", "4"))
    )
    semantic_scholar_retry_backoff_strategy: Literal["fixed", "linear", "exponential"] = Field(
        default_factory=lambda: cast(
            Literal["fixed", "linear", "exponential"],
            os.getenv("SEMANTIC_SCHOLAR_RETRY_BACKOFF_STRATEGY", "exponential"),
        )
    )
    semantic_scholar_retry_backoff_base_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SEMANTIC_SCHOLAR_RETRY_BACKOFF_BASE_SECONDS", "2.0"))
    )

    @field_validator(
        "llm_temperature",
        "openalex_calls_per_second",
        "semantic_scholar_calls_per_second",
        "crossref_calls_per_second",
        "springer_calls_per_second",
        "arxiv_calls_per_second",
        "pubmed_calls_per_second",
        "europe_pmc_calls_per_second",
        "core_calls_per_second",
        "unpaywall_calls_per_second",
        "google_scholar_calls_per_second",
        "semantic_scholar_request_delay_seconds",
        "semantic_scholar_retry_backoff_base_seconds",
    )
    @classmethod
    def validate_non_negative_float(cls, value: float) -> float:
        """Clamp float tuning parameters to non-negative values."""

        return max(float(value), 0.0)

    @field_validator("semantic_scholar_max_requests_per_minute", "semantic_scholar_retry_attempts")
    @classmethod
    def validate_provider_positive_int(cls, value: int) -> int:
        """Require positive integer values for provider-specific retry and throttling settings."""

        return max(int(value), 1)


class AnalysisPassConfig(BaseModel):
    """One screening pass in the configurable multi-pass analysis chain."""

    name: str
    llm_provider: Literal["heuristic", "openai_compatible", "gemini", "ollama", "huggingface_local"] = "heuristic"
    threshold: float = 70.0
    decision_mode: Literal["strict", "triage"] = "strict"
    maybe_threshold_margin: float = 10.0
    model_name: str | None = None
    min_input_score: float | None = None
    enabled: bool = True

    @field_validator("threshold", "maybe_threshold_margin")
    @classmethod
    def validate_score_like_fields(cls, value: float) -> float:
        """Clamp pass score-like values to the supported 0-100 range."""

        return min(max(float(value), 0.0), 100.0)

    @field_validator("min_input_score")
    @classmethod
    def validate_optional_min_input_score(cls, value: float | None) -> float | None:
        """Clamp optional per-pass entry-score gates to the supported 0-100 range."""

        if value is None:
            return None
        return min(max(float(value), 0.0), 100.0)


class ResearchConfig(BaseModel):
    """Validated runtime configuration shared across discovery, screening, and reporting."""

    research_topic: str
    research_question: str = ""
    review_objective: str = ""
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    banned_topics: list[str] = Field(default_factory=list)
    excluded_title_terms: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDED_TITLE_TERMS))
    search_keywords: list[str]
    boolean_operators: str | None = None
    pages_to_retrieve: int = 2
    results_per_page: int = 25
    discovery_strategy: Literal["precise", "balanced", "broad"] = "balanced"
    year_range_start: int = 2018
    year_range_end: int = 2026
    max_discovered_records: int | None = None
    min_discovered_records: int = 0
    max_papers_to_analyze: int = 50
    skip_discovery: bool = False
    citation_snowballing_enabled: bool = True
    relevance_threshold: float = 70.0
    download_pdfs: bool = False
    pdf_download_mode: Literal["all", "relevant_only"] = "all"
    analyze_full_text: bool = False
    full_text_max_chars: int = 12000
    llm_provider: Literal["auto", "heuristic", "openai_compatible", "gemini", "ollama", "huggingface_local"] = "auto"
    decision_mode: Literal["strict", "triage"] = "strict"
    maybe_threshold_margin: float = 10.0
    run_mode: Literal["collect", "analyze"] = "analyze"
    verbosity: Literal["normal", "verbose", "ultra_verbose"] = "normal"
    output_csv: bool = True
    output_json: bool = True
    output_markdown: bool = True
    output_sqlite_exports: bool = True
    ui_settings_mode: Literal["compact", "advanced"] = "compact"
    ui_show_advanced_settings: bool = False
    analysis_passes: list[AnalysisPassConfig] = Field(default_factory=list)
    openalex_enabled: bool = True
    semantic_scholar_enabled: bool = True
    crossref_enabled: bool = True
    springer_enabled: bool = False
    arxiv_enabled: bool = False
    include_pubmed: bool | None = None
    europe_pmc_enabled: bool = False
    core_enabled: bool = False
    google_scholar_enabled: bool = False
    google_scholar_pages: int = 1
    google_scholar_page_min: int = DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN
    google_scholar_page_max: int = DEFAULT_GOOGLE_SCHOLAR_PAGE_MAX
    google_scholar_results_per_page: int = 10
    topic_prefilter_enabled: bool = False
    topic_prefilter_filter_low_relevance: bool = False
    topic_prefilter_high_threshold: float = 0.75
    topic_prefilter_review_threshold: float = 0.55
    topic_prefilter_text_mode: Literal["title_only", "title_abstract", "title_abstract_full_text"] = "title_abstract"
    topic_prefilter_max_chars: int = 4000
    max_workers: int = 4
    discovery_workers: int = 0
    io_workers: int = 0
    screening_workers: int = 0
    request_timeout_seconds: int = 30
    partial_rerun_mode: Literal[
        "off",
        "reporting_only",
        "screening_and_reporting",
        "pdfs_screening_reporting",
    ] = "off"
    incremental_report_regeneration: bool = False
    enable_async_network_stages: bool = False
    http_cache_enabled: bool = True
    http_cache_dir: Path = Path("data/http_cache")
    http_cache_ttl_seconds: int = 86400
    http_retry_max_attempts: int = 4
    http_retry_base_delay_seconds: float = 1.0
    http_retry_max_delay_seconds: float = 30.0
    pdf_batch_size: int = 10
    resume_mode: bool = True
    reset_query_records: bool = False
    clear_screening_cache: bool = False
    disable_progress_bars: bool = False
    title_similarity_threshold: float = 0.92
    log_http_requests: bool = True
    log_http_payloads: bool = True
    log_llm_prompts: bool = True
    log_llm_responses: bool = True
    log_screening_decisions: bool = True
    profile_name: str | None = None
    fixture_data_path: Path | None = None
    manual_source_path: Path | None = None
    google_scholar_import_path: Path | None = None
    researchgate_import_path: Path | None = None
    data_dir: Path = Path("data")
    papers_dir: Path = Path("papers")
    relevant_pdfs_dir: Path | None = None
    results_dir: Path = Path("results")
    database_path: Path = Path("data/literature_review.db")
    log_file_path: Path | None = None
    api_settings: ApiSettings = Field(default_factory=ApiSettings)
    query_key: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_google_scholar_page_defaults(cls, value: Any) -> Any:
        """Populate dependent Scholar defaults before validation when only custom bounds are provided."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        page_min = payload.get("google_scholar_page_min", DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN)
        if payload.get("google_scholar_pages") in {None, ""}:
            payload["google_scholar_pages"] = page_min
        return payload

    @field_validator("search_keywords", mode="before")
    @classmethod
    def validate_keywords(cls, value: Any) -> list[str]:
        """Normalize keyword input from comma-separated strings or iterables."""

        return parse_search_terms(value)

    @field_validator("verbosity", mode="before")
    @classmethod
    def validate_verbosity(cls, value: Any) -> str:
        """Normalize legacy verbosity aliases and user-facing labels."""

        normalized = normalize_verbosity(str(value or "normal"))
        if normalized not in {"normal", "verbose", "ultra_verbose"}:
            raise ValueError("verbosity must be one of normal, verbose, or ultra_verbose")
        return normalized



    @field_validator("inclusion_criteria", "exclusion_criteria", "banned_topics", "excluded_title_terms", mode="before")
    @classmethod
    def validate_criteria(cls, value: Any) -> list[str]:
        """Normalize criteria-like fields into compact lists of non-empty strings."""

        return parse_search_terms(value)




    @field_validator("analysis_passes", mode="before")
    @classmethod
    def validate_analysis_passes(cls, value: Any) -> list[AnalysisPassConfig]:
        """Accept analysis passes from config objects, lists, or compact string forms."""

        if not value:
            return []
        if isinstance(value, list):
            normalized: list[AnalysisPassConfig] = []
            for item in value:
                if isinstance(item, AnalysisPassConfig):
                    normalized.append(item)
                elif isinstance(item, dict):
                    normalized.append(AnalysisPassConfig(**item))
                elif isinstance(item, str):
                    normalized.append(parse_analysis_pass(item))
            names = [item.name for item in normalized]
            if len(names) != len(set(names)):
                raise ValueError("analysis_passes must use unique pass names")
            return normalized
        if isinstance(value, str):
            return [parse_analysis_pass(value)]
        return []

    @field_validator("year_range_end")
    @classmethod
    def validate_year_range(cls, value: int, info: Any) -> int:
        """Reject year ranges whose end value falls before the configured start year."""

        year_start = info.data.get("year_range_start", value)
        if value < year_start:
            raise ValueError("year_range_end must be greater than or equal to year_range_start")
        return value


    @field_validator("topic_prefilter_high_threshold", "topic_prefilter_review_threshold")
    @classmethod
    def validate_similarity_fraction(cls, value: float) -> float:
        """Clamp semantic-similarity thresholds to the supported 0-1 range."""

        return min(max(float(value), 0.0), 1.0)

    @field_validator("relevance_threshold")
    @classmethod
    def validate_threshold(cls, value: float) -> float:
        """Clamp the global screening threshold to the supported 0-100 range."""

        return min(max(float(value), 0.0), 100.0)

    @field_validator("maybe_threshold_margin")
    @classmethod
    def validate_margin(cls, value: float) -> float:
        """Clamp the triage maybe-margin to the supported 0-100 range."""

        return min(max(float(value), 0.0), 100.0)

    @field_validator(
        "pages_to_retrieve",
        "results_per_page",
        "max_papers_to_analyze",
        "max_workers",
        "request_timeout_seconds",
        "full_text_max_chars",
        "http_cache_ttl_seconds",
        "http_retry_max_attempts",
        "pdf_batch_size",
        "google_scholar_pages",
        "google_scholar_page_min",
        "google_scholar_page_max",
        "google_scholar_results_per_page",
        "topic_prefilter_max_chars",
    )
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        """Require positive integer values for paging, sizing, and worker controls."""

        if int(value) < 1:
            raise ValueError("Configuration value must be at least 1")
        return int(value)

    @field_validator("http_retry_base_delay_seconds", "http_retry_max_delay_seconds")
    @classmethod
    def validate_non_negative_retry_delays(cls, value: float) -> float:
        """Require retry delay settings to stay at or above zero seconds."""

        if float(value) < 0:
            raise ValueError("Retry delay values must be at least 0")
        return float(value)

    @field_validator("discovery_workers", "io_workers", "screening_workers")
    @classmethod
    def validate_non_negative_worker_ints(cls, value: int) -> int:
        """Allow stage-specific worker overrides where zero means inherit the global worker count."""

        if int(value) < 0:
            raise ValueError("Worker override values must be at least 0")
        return int(value)

    @field_validator("title_similarity_threshold")
    @classmethod
    def validate_similarity_threshold(cls, value: float) -> float:
        """Clamp similarity thresholds to the supported 0-1 range."""

        return min(max(float(value), 0.0), 1.0)

    @field_validator("max_discovered_records")
    @classmethod
    def validate_optional_positive_int(cls, value: int | None) -> int | None:
        """Require positive integer values for optional discovery hard caps."""

        if value is None:
            return None
        if int(value) < 1:
            raise ValueError("Configuration value must be at least 1")
        return int(value)

    @field_validator("min_discovered_records")
    @classmethod
    def validate_non_negative_int(cls, value: int) -> int:
        """Require non-negative integer values for minimum discovery gates."""

        if int(value) < 0:
            raise ValueError("Configuration value must be at least 0")
        return int(value)

    @model_validator(mode="after")
    def validate_google_scholar_bounds(self) -> ResearchConfig:
        """Keep Google Scholar page-depth controls internally consistent."""

        if self.google_scholar_page_max < self.google_scholar_page_min:
            raise ValueError("google_scholar_page_max must be greater than or equal to google_scholar_page_min")
        if not self.google_scholar_page_min <= self.google_scholar_pages <= self.google_scholar_page_max:
            raise ValueError(
                "google_scholar_pages must be between "
                f"{self.google_scholar_page_min} and {self.google_scholar_page_max}"
            )
        return self

    @property
    def search_query(self) -> str:
        """Return the primary combined search query used across discovery sources."""

        return build_query(self.research_topic, self.search_keywords, self.boolean_operators)

    @property
    def per_source_limit(self) -> int:
        """Return the maximum number of papers any single source should contribute."""

        return self.pages_to_retrieve * self.results_per_page

    @property
    def discovery_queries(self) -> list[str]:
        """Expand the review brief into one or more unique queries per discovery strategy."""

        queries = [self.search_query]
        topic = self.research_topic.strip()
        keywords = [keyword.strip() for keyword in self.search_keywords if keyword.strip()]

        if self.discovery_strategy in {"balanced", "broad"} and topic:
            queries.append(topic)

        if self.discovery_strategy == "balanced" and keywords:
            queries.append(build_query(topic, keywords[: min(3, len(keywords))], "AND"))

        if self.discovery_strategy == "broad":
            queries.extend(build_query(topic, [keyword], "AND") for keyword in keywords[:5])
            if len(keywords) >= 2:
                queries.append(" OR ".join(keywords[: min(5, len(keywords))]))

        unique_queries: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = " ".join(query.split()).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_queries.append(normalized)
        return unique_queries

    @property
    def resolved_analysis_passes(self) -> list[AnalysisPassConfig]:
        """Resolve the active pass chain, including the implicit default screening pass."""

        if self.run_mode == "collect":
            return []
        if self.analysis_passes:
            return [analysis_pass for analysis_pass in self.analysis_passes if analysis_pass.enabled]
        provider = "heuristic" if self.llm_provider == "auto" else self.llm_provider
        return [
            AnalysisPassConfig(
                name="default",
                llm_provider=provider if provider != "auto" else "heuristic",
                threshold=self.relevance_threshold,
                decision_mode=self.decision_mode,
                maybe_threshold_margin=self.maybe_threshold_margin,
            )
        ]

    @property
    def screening_brief(self) -> str:
        """Build the review brief passed into screening and reporting components."""

        lines = [
            f"Research topic: {self.research_topic}",
            f"Search keywords: {', '.join(self.search_keywords)}",
        ]
        if self.research_question:
            lines.append(f"Research question: {self.research_question}")
        if self.review_objective:
            lines.append(f"Review objective: {self.review_objective}")
        if self.inclusion_criteria:
            lines.append(f"Inclusion criteria: {'; '.join(self.inclusion_criteria)}")
        if self.exclusion_criteria:
            lines.append(f"Exclusion criteria: {'; '.join(self.exclusion_criteria)}")
        if self.banned_topics:
            lines.append(f"Banned topics: {'; '.join(self.banned_topics)}")
        if self.excluded_title_terms:
            lines.append(f"Excluded title terms: {'; '.join(self.excluded_title_terms)}")
        lines.append(f"Discovery strategy: {self.discovery_strategy}")
        if self.max_discovered_records is not None:
            lines.append(f"Maximum discovered records: {self.max_discovered_records}")
        if self.min_discovered_records:
            lines.append(f"Minimum discovered records: {self.min_discovered_records}")
        if self.google_scholar_enabled:
            lines.append(f"Google Scholar pages: {self.google_scholar_pages}")
        if self.topic_prefilter_enabled:
            lines.append(
                "Local topic prefilter: "
                f"{self.api_settings.topic_prefilter_model} with review threshold {self.topic_prefilter_review_threshold:.2f} "
                f"and high threshold {self.topic_prefilter_high_threshold:.2f}"
            )
        return "\n".join(lines)

    @property
    def screening_context_key(self) -> str:
        """Return a stable cache key for the current screening context and pass chain."""

        components = [
            SCREENING_ALGORITHM_VERSION,
            self.research_topic,
            self.research_question,
            self.review_objective,
            ",".join(sorted(self.search_keywords)),
            ",".join(sorted(self.inclusion_criteria)),
            ",".join(sorted(self.exclusion_criteria)),
            ",".join(sorted(self.banned_topics)),
            ",".join(sorted(self.excluded_title_terms)),
            self.discovery_strategy,
            self.decision_mode,
            str(self.relevance_threshold),
            str(self.maybe_threshold_margin),
            str(self.analyze_full_text),
            self.llm_provider,
            self.run_mode,
            str(self.google_scholar_enabled),
            str(self.google_scholar_pages),
            str(self.google_scholar_results_per_page),
            str(self.topic_prefilter_enabled),
            str(self.topic_prefilter_filter_low_relevance),
            str(self.topic_prefilter_high_threshold),
            str(self.topic_prefilter_review_threshold),
            self.topic_prefilter_text_mode,
            str(self.topic_prefilter_max_chars),
            self.api_settings.topic_prefilter_model,
            json.dumps([analysis_pass.model_dump(mode="json") for analysis_pass in self.resolved_analysis_passes]),
        ]
        return make_query_key("|".join(components), [], self.year_range_start, self.year_range_end)

    @property
    def effective_discovery_workers(self) -> int:
        """Return the worker count used for discovery-stage parallelism."""

        return self.discovery_workers or self.max_workers

    @property
    def effective_io_workers(self) -> int:
        """Return the worker count used for IO-heavy paper stages such as PDF enrichment."""

        return self.io_workers or self.max_workers

    @property
    def effective_screening_workers(self) -> int:
        """Return the worker count used for AI-screening parallelism before provider-specific caps."""

        return self.screening_workers or self.max_workers

    def finalize(self) -> "ResearchConfig":
        """Resolve derived values and ensure the configured output directories exist."""

        include_pubmed = self._infer_pubmed() if self.include_pubmed is None else self.include_pubmed
        query_key = self.query_key or make_query_key(
            self.research_topic,
            self.search_keywords,
            self.year_range_start,
            self.year_range_end,
        )
        relevant_pdfs_dir = self.relevant_pdfs_dir or (self.papers_dir / "relevant")
        http_cache_dir = self.http_cache_dir or (self.data_dir / "http_cache")
        log_file_path = build_log_file_path(results_dir=self.results_dir, explicit_path=self.log_file_path)
        updated = self.model_copy(
            update={
                "include_pubmed": include_pubmed,
                "query_key": query_key,
                "relevant_pdfs_dir": relevant_pdfs_dir,
                "http_cache_dir": http_cache_dir,
                "log_file_path": log_file_path,
                "verbosity": normalize_verbosity(self.verbosity),
            }
        )
        updated.ensure_directories()
        return updated

    def ensure_directories(self) -> None:
        """Create all configured filesystem locations needed by the pipeline."""

        paths = [self.data_dir, self.papers_dir, self.results_dir]
        if self.relevant_pdfs_dir:
            paths.append(self.relevant_pdfs_dir)
        if self.http_cache_enabled:
            paths.append(self.http_cache_dir)
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        ensure_parent_directory(self.database_path)
        if self.log_file_path is not None:
            ensure_parent_directory(self.log_file_path)

    def save_snapshot(self) -> Path:
        """Persist a redacted copy of the active configuration alongside the run outputs."""

        target = self.results_dir / "run_config.json"
        payload = self.model_dump(mode="json")
        api_settings = payload.get("api_settings", {})
        for key in ("semantic_scholar_api_key", "springer_api_key", "openai_api_key", "gemini_api_key", "ollama_api_key"):
            if api_settings.get(key):
                api_settings[key] = "***REDACTED***"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def _infer_pubmed(self) -> bool:
        """Enable PubMed automatically for clearly biomedical topics when not set explicitly."""

        haystack = " ".join([self.research_topic, *self.search_keywords]).lower()
        return any(term in haystack for term in BIOMEDICAL_TERMS)

    @classmethod
    def from_cli(cls, args: argparse.Namespace) -> "ResearchConfig":
        """Build a validated config from CLI flags, config files, and interactive prompts."""

        file_config = cls._load_config_file(args.config_file) if args.config_file else {}

        def ask(prompt: str, default: str | None = None) -> str:
            suffix = f" [{default}]" if default is not None else ""
            value = input(f"{prompt}{suffix}: ").strip()
            return value or (default or "")

        def ask_int(prompt: str, default: int) -> int:
            while True:
                raw = ask(prompt, str(default))
                try:
                    return int(raw)
                except ValueError:
                    print("Please enter a valid integer.")

        def ask_float(prompt: str, default: float) -> float:
            while True:
                raw = ask(prompt, str(default))
                try:
                    return float(raw)
                except ValueError:
                    print("Please enter a valid number.")

        def ask_bool(prompt: str, default: bool) -> bool:
            default_label = "yes" if default else "no"
            while True:
                raw = ask(prompt, default_label).lower()
                if raw in {"yes", "y"}:
                    return True
                if raw in {"no", "n"}:
                    return False
                print("Please answer yes or no.")

        def value_for(name: str, cli_value: Any, default: Any = None) -> Any:
            if cli_value is not None:
                return cli_value
            if name in file_config:
                return file_config[name]
            return default

        topic = value_for("research_topic", getattr(args, "research_topic", None))
        if not topic:
            topic = ask("Enter research topic")

        research_question = value_for("research_question", getattr(args, "research_question", None), "")
        if (
            not args.config_file
            and getattr(args, "research_question", None) is None
            and "research_question" not in file_config
        ):
            research_question = ask("Optional research question", "")

        review_objective = value_for("review_objective", getattr(args, "review_objective", None), "")
        if (
            not args.config_file
            and getattr(args, "review_objective", None) is None
            and "review_objective" not in file_config
        ):
            review_objective = ask("Optional review objective", "")

        keywords = value_for("search_keywords", getattr(args, "search_keywords", None))
        if not keywords:
            keywords = ask("Enter search keywords separated by comma")

        inclusion_criteria = value_for("inclusion_criteria", getattr(args, "inclusion_criteria", None), [])
        if (
            not args.config_file
            and getattr(args, "inclusion_criteria", None) is None
            and "inclusion_criteria" not in file_config
        ):
            raw_inclusion = ask("Optional inclusion criteria separated by semicolon", "")
            inclusion_criteria = parse_search_terms(raw_inclusion)

        exclusion_criteria = value_for("exclusion_criteria", getattr(args, "exclusion_criteria", None), [])
        if (
            not args.config_file
            and getattr(args, "exclusion_criteria", None) is None
            and "exclusion_criteria" not in file_config
        ):
            raw_exclusion = ask("Optional exclusion criteria separated by semicolon", "")
            exclusion_criteria = parse_search_terms(raw_exclusion)

        banned_topics = value_for("banned_topics", getattr(args, "banned_topics", None), [])
        if not args.config_file and getattr(args, "banned_topics", None) is None and "banned_topics" not in file_config:
            raw_banned = ask("Optional banned topics separated by semicolon", "")
            banned_topics = parse_search_terms(raw_banned)

        excluded_title_terms = value_for(
            "excluded_title_terms",
            getattr(args, "excluded_title_terms", None),
            list(DEFAULT_EXCLUDED_TITLE_TERMS),
        )
        if (
                not args.config_file
                and getattr(args, "excluded_title_terms", None) is None
                and "excluded_title_terms" not in file_config
        ):
            raw_excluded_titles = ask(
                "Optional excluded title terms separated by semicolon",
                "; ".join(DEFAULT_EXCLUDED_TITLE_TERMS),
            )
            excluded_title_terms = parse_search_terms(raw_excluded_titles)

        boolean_operators = value_for("boolean_operators", getattr(args, "boolean_operators", None), "AND")
        if getattr(args, "boolean_operators", None) is None and "boolean_operators" not in file_config:
            boolean_operators = ask("Optional boolean operator or expression", "AND")

        pages_to_retrieve = value_for("pages_to_retrieve", getattr(args, "pages_to_retrieve", None))
        if pages_to_retrieve is None:
            pages_to_retrieve = ask_int("Number of pages or result batches to retrieve per source", 2)

        results_per_page = value_for("results_per_page", args.results_per_page, 25)

        year_start = value_for("year_range_start", getattr(args, "year_range_start", None))
        if year_start is None:
            year_start = ask_int("Year range start", 2018)

        year_end = value_for("year_range_end", getattr(args, "year_range_end", None))
        if year_end is None:
            year_end = ask_int("Year range end", 2026)

        max_papers = value_for("max_papers_to_analyze", getattr(args, "max_papers_to_analyze", None))
        if max_papers is None:
            max_papers = ask_int("Max results to analyze", 50)

        citation_snowballing = (
            getattr(args, "citation_snowballing_enabled", None)
            if getattr(args, "citation_snowballing_enabled", None) is not None
            else file_config.get("citation_snowballing_enabled")
        )
        if citation_snowballing is None:
            citation_snowballing = ask_bool("Enable citation snowballing? (yes/no)", True)

        relevance_threshold = (
            getattr(args, "relevance_threshold", None)
            if getattr(args, "relevance_threshold", None) is not None
            else file_config.get("relevance_threshold")
        )
        if relevance_threshold is None:
            relevance_threshold = ask_float("Relevance score threshold", 70.0)

        download_pdfs = args.download_pdfs if args.download_pdfs is not None else file_config.get("download_pdfs")
        if download_pdfs is None:
            download_pdfs = ask_bool("Download PDFs if available? (yes/no)", False)

        analyze_full_text = (
            args.analyze_full_text
            if getattr(args, "analyze_full_text", None) is not None
            else file_config.get("analyze_full_text")
        )
        if analyze_full_text is None and not args.config_file:
            analyze_full_text = ask_bool("Analyze full text from PDFs when available? (yes/no)", False)
        elif analyze_full_text is None:
            analyze_full_text = False

        include_pubmed = args.include_pubmed if args.include_pubmed is not None else file_config.get("include_pubmed")
        if include_pubmed is None:
            include_pubmed = ask_bool("Include PubMed if the query is biomedical? (yes/no)", True)

        run_mode = value_for("run_mode", getattr(args, "run_mode", None), "analyze")
        verbosity = cast(
            Literal["normal", "verbose", "ultra_verbose"],
            normalize_verbosity(value_for("verbosity", getattr(args, "verbosity", None), "normal")),
        )
        if getattr(args, "ultra_verbose", False):
            verbosity = "ultra_verbose"
        elif getattr(args, "verbose_flag", False):
            verbosity = "verbose"
        analysis_passes = value_for("analysis_passes", getattr(args, "analysis_passes", None), [])
        file_api_settings = file_config.get("api_settings", {}) or {}
        api_overrides = {
            key: value
            for key, value in {
                "semantic_scholar_api_key": getattr(args, "semantic_scholar_api_key", None),
                "crossref_mailto": getattr(args, "crossref_mailto", None),
                "unpaywall_email": getattr(args, "unpaywall_email", None),
                "springer_api_key": getattr(args, "springer_api_key", None),
                "core_api_key": getattr(args, "core_api_key", None),
                "openai_api_key": getattr(args, "openai_api_key", None),
                "openai_base_url": getattr(args, "openai_base_url", None),
                "openai_model": getattr(args, "openai_model", None),
                "gemini_api_key": getattr(args, "gemini_api_key", None),
                "gemini_base_url": getattr(args, "gemini_base_url", None),
                "gemini_model": getattr(args, "gemini_model", None),
                "ollama_base_url": getattr(args, "ollama_base_url", None),
                "ollama_model": getattr(args, "ollama_model", None),
                "ollama_api_key": getattr(args, "ollama_api_key", None),
                "huggingface_model": getattr(args, "huggingface_model", None),
                "huggingface_task": getattr(args, "huggingface_task", None),
                "huggingface_device": getattr(args, "huggingface_device", None),
                "huggingface_dtype": getattr(args, "huggingface_dtype", None),
                "huggingface_max_new_tokens": getattr(args, "huggingface_max_new_tokens", None),
                "huggingface_cache_dir": getattr(args, "huggingface_cache_dir", None),
                "huggingface_trust_remote_code": getattr(args, "huggingface_trust_remote_code", None),
                "llm_temperature": getattr(args, "llm_temperature", None),
                "openalex_calls_per_second": getattr(args, "openalex_calls_per_second", None),
                "semantic_scholar_calls_per_second": getattr(args, "semantic_scholar_calls_per_second", None),
                "crossref_calls_per_second": getattr(args, "crossref_calls_per_second", None),
                "springer_calls_per_second": getattr(args, "springer_calls_per_second", None),
                "arxiv_calls_per_second": getattr(args, "arxiv_calls_per_second", None),
                "pubmed_calls_per_second": getattr(args, "pubmed_calls_per_second", None),
                "europe_pmc_calls_per_second": getattr(args, "europe_pmc_calls_per_second", None),
                "core_calls_per_second": getattr(args, "core_calls_per_second", None),
                "unpaywall_calls_per_second": getattr(args, "unpaywall_calls_per_second", None),
                "topic_prefilter_model": getattr(args, "topic_prefilter_model", None),
                "google_scholar_calls_per_second": getattr(args, "google_scholar_calls_per_second", None),
                "semantic_scholar_max_requests_per_minute": getattr(args, "semantic_scholar_max_requests_per_minute", None),
                "semantic_scholar_request_delay_seconds": getattr(args, "semantic_scholar_request_delay_seconds", None),
                "semantic_scholar_retry_attempts": getattr(args, "semantic_scholar_retry_attempts", None),
                "semantic_scholar_retry_backoff_strategy": getattr(args, "semantic_scholar_retry_backoff_strategy", None),
                "semantic_scholar_retry_backoff_base_seconds": getattr(args, "semantic_scholar_retry_backoff_base_seconds", None),
            }.items()
            if value is not None
        }
        api_settings = ApiSettings(**{**file_api_settings, **api_overrides})
        google_scholar_page_min = value_for(
            "google_scholar_page_min",
            getattr(args, "google_scholar_page_min", None),
            DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN,
        )
        google_scholar_page_max = value_for(
            "google_scholar_page_max",
            getattr(args, "google_scholar_page_max", None),
            DEFAULT_GOOGLE_SCHOLAR_PAGE_MAX,
        )
        google_scholar_pages = value_for(
            "google_scholar_pages",
            getattr(args, "google_scholar_pages", None),
            max(DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN, int(google_scholar_page_min)),
        )

        return cls(
            research_topic=topic,
            research_question=research_question,
            review_objective=review_objective,
            inclusion_criteria=inclusion_criteria,
            exclusion_criteria=exclusion_criteria,
            banned_topics=banned_topics,
            excluded_title_terms=excluded_title_terms,
            search_keywords=keywords,
            boolean_operators=boolean_operators,
            pages_to_retrieve=pages_to_retrieve,
            results_per_page=results_per_page,
            year_range_start=year_start,
            year_range_end=year_end,
            max_papers_to_analyze=max_papers,
            skip_discovery=value_for("skip_discovery", getattr(args, "skip_discovery", None), False),
            max_discovered_records=value_for(
                "max_discovered_records",
                getattr(args, "max_discovered_records", None),
                None,
            ),
            min_discovered_records=value_for(
                "min_discovered_records",
                getattr(args, "min_discovered_records", None),
                0,
            ),
            citation_snowballing_enabled=citation_snowballing,
            relevance_threshold=relevance_threshold,
            download_pdfs=download_pdfs,
            pdf_download_mode=value_for("pdf_download_mode", getattr(args, "pdf_download_mode", None), "all"),
            analyze_full_text=analyze_full_text,
            full_text_max_chars=value_for("full_text_max_chars", getattr(args, "full_text_max_chars", None), 12000),
            llm_provider=value_for("llm_provider", getattr(args, "llm_provider", None), "auto"),
            decision_mode=value_for("decision_mode", getattr(args, "decision_mode", None), "strict"),
            maybe_threshold_margin=value_for(
                "maybe_threshold_margin",
                getattr(args, "maybe_threshold_margin", None),
                10.0,
            ),
            run_mode=run_mode,
            verbosity=verbosity,
            discovery_strategy=value_for(
                "discovery_strategy",
                getattr(args, "discovery_strategy", None),
                "balanced",
            ),
            output_csv=value_for("output_csv", getattr(args, "output_csv", None), True),
            output_json=value_for("output_json", getattr(args, "output_json", None), True),
            output_markdown=value_for("output_markdown", getattr(args, "output_markdown", None), True),
            output_sqlite_exports=value_for(
                "output_sqlite_exports",
                getattr(args, "output_sqlite_exports", None),
                True,
            ),
            ui_settings_mode=value_for("ui_settings_mode", getattr(args, "ui_settings_mode", None), "compact"),
            ui_show_advanced_settings=value_for(
                "ui_show_advanced_settings",
                getattr(args, "ui_show_advanced_settings", None),
                False,
            ),
            analysis_passes=analysis_passes,
            openalex_enabled=value_for("openalex_enabled", args.openalex_enabled, True),
            semantic_scholar_enabled=value_for("semantic_scholar_enabled", args.semantic_scholar_enabled, True),
            crossref_enabled=value_for("crossref_enabled", args.crossref_enabled, True),
            springer_enabled=value_for("springer_enabled", getattr(args, "springer_enabled", None), False),
            arxiv_enabled=value_for("arxiv_enabled", getattr(args, "arxiv_enabled", None), False),
            include_pubmed=include_pubmed,
            europe_pmc_enabled=value_for("europe_pmc_enabled", getattr(args, "europe_pmc_enabled", None), False),
            core_enabled=value_for("core_enabled", getattr(args, "core_enabled", None), False),
            google_scholar_enabled=value_for("google_scholar_enabled", getattr(args, "google_scholar_enabled", None), False),
            google_scholar_pages=google_scholar_pages,
            google_scholar_page_min=google_scholar_page_min,
            google_scholar_page_max=google_scholar_page_max,
            google_scholar_results_per_page=value_for("google_scholar_results_per_page", getattr(args, "google_scholar_results_per_page", None), 10),
            topic_prefilter_enabled=value_for("topic_prefilter_enabled", getattr(args, "topic_prefilter_enabled", None), False),
            topic_prefilter_filter_low_relevance=value_for("topic_prefilter_filter_low_relevance", getattr(args, "topic_prefilter_filter_low_relevance", None), False),
            topic_prefilter_high_threshold=value_for("topic_prefilter_high_threshold", getattr(args, "topic_prefilter_high_threshold", None), 0.75),
            topic_prefilter_review_threshold=value_for("topic_prefilter_review_threshold", getattr(args, "topic_prefilter_review_threshold", None), 0.55),
            topic_prefilter_text_mode=value_for("topic_prefilter_text_mode", getattr(args, "topic_prefilter_text_mode", None), "title_abstract"),
            topic_prefilter_max_chars=value_for("topic_prefilter_max_chars", getattr(args, "topic_prefilter_max_chars", None), 4000),
            max_workers=value_for("max_workers", args.max_workers, 4),
            discovery_workers=value_for("discovery_workers", getattr(args, "discovery_workers", None), 0),
            io_workers=value_for("io_workers", getattr(args, "io_workers", None), 0),
            screening_workers=value_for("screening_workers", getattr(args, "screening_workers", None), 0),
            request_timeout_seconds=value_for("request_timeout_seconds", args.request_timeout_seconds, 30),
            partial_rerun_mode=value_for(
                "partial_rerun_mode",
                getattr(args, "partial_rerun_mode", None),
                "off",
            ),
            incremental_report_regeneration=value_for(
                "incremental_report_regeneration",
                getattr(args, "incremental_report_regeneration", None),
                False,
            ),
            enable_async_network_stages=value_for(
                "enable_async_network_stages",
                getattr(args, "enable_async_network_stages", None),
                False,
            ),
            http_cache_enabled=value_for(
                "http_cache_enabled",
                getattr(args, "http_cache_enabled", None),
                True,
            ),
            http_cache_dir=value_for(
                "http_cache_dir",
                getattr(args, "http_cache_dir", None),
                Path("data/http_cache"),
            ),
            http_cache_ttl_seconds=value_for(
                "http_cache_ttl_seconds",
                getattr(args, "http_cache_ttl_seconds", None),
                86400,
            ),
            http_retry_max_attempts=value_for(
                "http_retry_max_attempts",
                getattr(args, "http_retry_max_attempts", None),
                4,
            ),
            http_retry_base_delay_seconds=value_for(
                "http_retry_base_delay_seconds",
                getattr(args, "http_retry_base_delay_seconds", None),
                1.0,
            ),
            http_retry_max_delay_seconds=value_for(
                "http_retry_max_delay_seconds",
                getattr(args, "http_retry_max_delay_seconds", None),
                30.0,
            ),
            pdf_batch_size=value_for(
                "pdf_batch_size",
                getattr(args, "pdf_batch_size", None),
                10,
            ),
            resume_mode=value_for("resume_mode", args.resume_mode, True),
            reset_query_records=value_for("reset_query_records", getattr(args, "reset_query_records", None), False),
            clear_screening_cache=value_for(
                "clear_screening_cache",
                getattr(args, "clear_screening_cache", None),
                False,
            ),
            disable_progress_bars=value_for("disable_progress_bars", args.disable_progress_bars, False),
            title_similarity_threshold=value_for(
                "title_similarity_threshold",
                args.title_similarity_threshold,
                0.92,
            ),
            log_http_requests=value_for(
                "log_http_requests",
                getattr(args, "log_http_requests", None),
                True,
            ),
            log_http_payloads=value_for(
                "log_http_payloads",
                getattr(args, "log_http_payloads", None),
                True,
            ),
            log_llm_prompts=value_for(
                "log_llm_prompts",
                getattr(args, "log_llm_prompts", None),
                True,
            ),
            log_llm_responses=value_for(
                "log_llm_responses",
                getattr(args, "log_llm_responses", None),
                True,
            ),
            log_screening_decisions=value_for(
                "log_screening_decisions",
                getattr(args, "log_screening_decisions", None),
                True,
            ),
            profile_name=value_for("profile_name", getattr(args, "profile_name", None), None),
            fixture_data_path=value_for("fixture_data_path", getattr(args, "fixture_data_path", None)),
            manual_source_path=value_for("manual_source_path", getattr(args, "manual_source_path", None)),
            google_scholar_import_path=value_for(
                "google_scholar_import_path",
                getattr(args, "google_scholar_import_path", None),
            ),
            researchgate_import_path=value_for(
                "researchgate_import_path",
                getattr(args, "researchgate_import_path", None),
            ),
            data_dir=value_for("data_dir", getattr(args, "data_dir", None), Path("data")),
            papers_dir=value_for("papers_dir", getattr(args, "papers_dir", None), Path("papers")),
            relevant_pdfs_dir=value_for(
                "relevant_pdfs_dir",
                getattr(args, "relevant_pdfs_dir", None),
                None,
            ),
            results_dir=value_for("results_dir", getattr(args, "results_dir", None), Path("results")),
            database_path=value_for(
                "database_path",
                getattr(args, "database_path", None),
                Path("data/literature_review.db"),
            ),
            log_file_path=value_for("log_file_path", getattr(args, "log_file_path", None), None),
            api_settings=api_settings,
        ).finalize()

    @staticmethod
    def _load_config_file(config_path: str) -> dict[str, Any]:
        """Load a JSON configuration file used by CLI and UI entrypoints."""

        path = Path(config_path)
        return json.loads(path.read_text(encoding="utf-8"))


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the shared command-line parser for scripted and interactive startup paths."""

    parser = argparse.ArgumentParser(description="Systematic literature discovery and screening pipeline")
    parser.add_argument("--config-file", help="Load run settings from a JSON config file")
    parser.add_argument("--ui", action="store_true", help="Launch the guided Tkinter desktop workbench")
    parser.add_argument("--wizard", action="store_true", help="Force the classic text-based interactive wizard")
    parser.add_argument("--topic", dest="research_topic", help="Research topic")
    parser.add_argument("--research-question", help="Explicit research question for AI screening")
    parser.add_argument("--review-objective", help="Review objective or intended output")
    parser.add_argument("--inclusion-criteria", help="Semicolon-separated inclusion criteria")
    parser.add_argument("--exclusion-criteria", help="Semicolon-separated exclusion criteria")
    parser.add_argument("--banned-topics", help="Semicolon-separated banned topics or themes")
    parser.add_argument(
        "--excluded-title-terms",
        help="Semicolon-separated title markers that should be excluded, for example correction;erratum;editorial",
    )
    parser.add_argument("--keywords", dest="search_keywords", help="Comma-separated search keywords")
    parser.add_argument("--boolean", dest="boolean_operators", help="Boolean operator or expression to join keywords")
    parser.add_argument("--pages", type=int, dest="pages_to_retrieve", help="Number of pages or result batches per source")
    parser.add_argument("--results-per-page", type=int, dest="results_per_page", help="Results fetched per source page")
    parser.add_argument(
        "--discovery-strategy",
        choices=["precise", "balanced", "broad"],
        help="Control how many query variants are issued to each discovery source",
    )
    parser.add_argument("--year-start", type=int, dest="year_range_start", help="Publication year range start")
    parser.add_argument("--year-end", type=int, dest="year_range_end", help="Publication year range end")
    parser.add_argument(
        "--max-discovered-records",
        type=int,
        dest="max_discovered_records",
        help="Hard cap on globally discovered unique records after deduplication",
    )
    parser.add_argument(
        "--min-discovered-records",
        type=int,
        dest="min_discovered_records",
        help="Hard minimum number of unique records required before screening continues",
    )
    parser.add_argument("--max-papers", type=int, dest="max_papers_to_analyze", help="Maximum papers to analyze")
    parser.add_argument(
        "--skip-discovery",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Skip new discovery and continue from already stored records for this query",
    )
    parser.add_argument(
        "--citation-snowballing",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="citation_snowballing_enabled",
        help="Enable or disable backward and forward citation expansion",
    )
    parser.add_argument(
        "--download-pdfs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Download PDFs through Unpaywall and direct open-access links",
    )
    parser.add_argument(
        "--pdf-download-mode",
        choices=["all", "relevant_only"],
        help="Download PDFs for all discoverable papers or only for papers that pass the relevance threshold",
    )
    parser.add_argument(
        "--analyze-full-text",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Extract and analyze PDF full text when available",
    )
    parser.add_argument(
        "--include-pubmed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force PubMed discovery on or off",
    )
    parser.add_argument(
        "--openalex-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable OpenAlex discovery",
    )
    parser.add_argument(
        "--semantic-scholar-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable Semantic Scholar discovery",
    )
    parser.add_argument(
        "--crossref-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable Crossref discovery",
    )
    parser.add_argument(
        "--springer-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable Springer Nature metadata API discovery",
    )
    parser.add_argument(
        "--arxiv-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable arXiv API discovery",
    )
    parser.add_argument(
        "--europe-pmc-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable Europe PMC discovery",
    )
    parser.add_argument(
        "--core-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable CORE discovery",
    )
    parser.add_argument("--threshold", type=float, dest="relevance_threshold", help="Relevance score threshold from 0 to 100")
    parser.add_argument(
        "--google-scholar-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable experimental Google Scholar HTML discovery",
    )
    parser.add_argument(
        "--google-scholar-pages",
        type=int,
        dest="google_scholar_pages",
        help=(
            f"Number of Google Scholar result pages to process when Scholar discovery is enabled "
            f"({DEFAULT_GOOGLE_SCHOLAR_PAGE_MIN}-{DEFAULT_GOOGLE_SCHOLAR_PAGE_MAX} by default)"
        ),
    )
    parser.add_argument(
        "--google-scholar-page-min",
        type=int,
        dest="google_scholar_page_min",
        help="Lower bound applied when validating the configured Google Scholar page depth",
    )
    parser.add_argument(
        "--google-scholar-page-max",
        type=int,
        dest="google_scholar_page_max",
        help="Upper bound applied when validating the configured Google Scholar page depth",
    )
    parser.add_argument(
        "--google-scholar-results-per-page",
        type=int,
        dest="google_scholar_results_per_page",
        help="Expected Google Scholar result count per page when calculating offsets",
    )
    parser.add_argument(
        "--topic-prefilter-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable the local MiniLM semantic topic gate before deeper screening",
    )
    parser.add_argument(
        "--topic-prefilter-filter-low-relevance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Automatically exclude papers whose local semantic topic label is LOW_RELEVANCE",
    )
    parser.add_argument(
        "--topic-prefilter-high-threshold",
        type=float,
        dest="topic_prefilter_high_threshold",
        help="Semantic similarity threshold for HIGH_RELEVANCE in the local MiniLM topic gate",
    )
    parser.add_argument(
        "--topic-prefilter-review-threshold",
        type=float,
        dest="topic_prefilter_review_threshold",
        help="Semantic similarity threshold for REVIEW in the local MiniLM topic gate",
    )
    parser.add_argument(
        "--topic-prefilter-text-mode",
        choices=["title_only", "title_abstract", "title_abstract_full_text"],
        help="Paper text window used by the local MiniLM topic gate",
    )
    parser.add_argument(
        "--topic-prefilter-max-chars",
        type=int,
        dest="topic_prefilter_max_chars",
        help="Maximum number of paper characters passed into the local MiniLM topic gate",
    )
    parser.add_argument(
        "--topic-prefilter-model",
        help="Local Hugging Face sentence-embedding model used for the MiniLM-style topic gate",
    )
    parser.add_argument(
        "--run-mode",
        choices=["collect", "analyze"],
        help="Collect metadata only or run full analysis",
    )
    parser.add_argument(
        "--ui-settings-mode",
        choices=["compact", "advanced"],
        help="Default settings density used when the guided desktop workbench opens",
    )
    parser.add_argument(
        "--ui-show-advanced-settings",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Reveal or hide advanced settings pages by default when the guided desktop workbench opens",
    )
    parser.add_argument(
        "--verbosity",
        choices=["normal", "verbose", "ultra_verbose", "debug", "quiet"],
        help=(
            "Logging mode. 'normal' shows major stages and outcomes, 'verbose' adds substeps and source activity, "
            "and 'ultra_verbose' adds TRACE-style diagnostics such as parsed results, retries, and timing."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        dest="verbose_flag",
        help="Shortcut for --verbosity verbose with detailed operational logging.",
    )
    parser.add_argument(
        "--ultra-verbose",
        action="store_true",
        dest="ultra_verbose",
        help="Shortcut for --verbosity ultra_verbose with TRACE-style diagnostics.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "heuristic", "openai_compatible", "gemini", "ollama", "huggingface_local"],
        help="LLM provider mode for screening",
    )
    parser.add_argument(
        "--analysis-pass",
        action="append",
        dest="analysis_passes",
        help="Sequential analysis pass in the form name:provider:threshold[:decision_mode[:margin]] or the extended UI pipe format",
    )
    parser.add_argument("--semantic-scholar-api-key", help="Semantic Scholar API key")
    parser.add_argument("--crossref-mailto", help="Contact email sent with Crossref requests")
    parser.add_argument("--unpaywall-email", help="Contact email required for Unpaywall PDF lookups")
    parser.add_argument("--springer-api-key", help="Springer Nature API key")
    parser.add_argument("--core-api-key", help="Optional CORE API key")
    parser.add_argument("--openai-api-key", help="API key for OpenAI-compatible endpoints")
    parser.add_argument("--openai-base-url", help="OpenAI-compatible base URL")
    parser.add_argument("--openai-model", help="OpenAI model name, default gpt-5.4")
    parser.add_argument("--openalex-calls-per-second", type=float, dest="openalex_calls_per_second", help="Rate limit for OpenAlex requests")
    parser.add_argument(
        "--semantic-scholar-calls-per-second",
        type=float,
        dest="semantic_scholar_calls_per_second",
        help="Rate limit for Semantic Scholar requests",
    )
    parser.add_argument("--crossref-calls-per-second", type=float, dest="crossref_calls_per_second", help="Rate limit for Crossref requests")
    parser.add_argument("--springer-calls-per-second", type=float, dest="springer_calls_per_second", help="Rate limit for Springer requests")
    parser.add_argument("--arxiv-calls-per-second", type=float, dest="arxiv_calls_per_second", help="Rate limit for arXiv requests")
    parser.add_argument("--pubmed-calls-per-second", type=float, dest="pubmed_calls_per_second", help="Rate limit for PubMed requests")
    parser.add_argument(
        "--europe-pmc-calls-per-second",
        type=float,
        dest="europe_pmc_calls_per_second",
        help="Rate limit for Europe PMC requests",
    )
    parser.add_argument("--core-calls-per-second", type=float, dest="core_calls_per_second", help="Rate limit for CORE requests")
    parser.add_argument("--unpaywall-calls-per-second", type=float, dest="unpaywall_calls_per_second", help="Rate limit for Unpaywall requests")
    parser.add_argument("--google-scholar-calls-per-second", type=float, dest="google_scholar_calls_per_second", help="Rate limit for Google Scholar page requests")
    parser.add_argument("--semantic-scholar-max-requests-per-minute", type=int, dest="semantic_scholar_max_requests_per_minute", help="Proactive Semantic Scholar request ceiling per minute")
    parser.add_argument("--semantic-scholar-request-delay-seconds", type=float, dest="semantic_scholar_request_delay_seconds", help="Minimum extra delay between Semantic Scholar requests")
    parser.add_argument("--semantic-scholar-retry-attempts", type=int, dest="semantic_scholar_retry_attempts", help="Semantic Scholar retry attempts after 429 responses")
    parser.add_argument("--semantic-scholar-retry-backoff-strategy", choices=["fixed", "linear", "exponential"], dest="semantic_scholar_retry_backoff_strategy", help="Backoff strategy used for Semantic Scholar retries")
    parser.add_argument("--semantic-scholar-retry-backoff-base-seconds", type=float, dest="semantic_scholar_retry_backoff_base_seconds", help="Base backoff delay for Semantic Scholar retries")
    parser.add_argument("--gemini-api-key", help="Google Gemini API key")
    parser.add_argument("--gemini-base-url", help="Gemini Generative Language API base URL")
    parser.add_argument("--gemini-model", help="Gemini model name, default gemini-2.5-flash")
    parser.add_argument("--ollama-base-url", help="Ollama OpenAI-compatible base URL")
    parser.add_argument("--ollama-model", help="Ollama model tag, for example qwen3:8b or gpt-oss:20b")
    parser.add_argument("--ollama-api-key", help="Optional API key for Ollama-compatible gateways")
    parser.add_argument(
        "--huggingface-model",
        help="Hugging Face model id for local inference, for example Qwen/Qwen3-14B or openai/gpt-oss-20b",
    )
    parser.add_argument(
        "--huggingface-task",
        help="Transformers pipeline task for local inference, default text-generation",
    )
    parser.add_argument(
        "--huggingface-device",
        help="Transformers device or device_map setting, default auto",
    )
    parser.add_argument(
        "--huggingface-dtype",
        help="Transformers torch dtype string, for example auto, float16, bfloat16",
    )
    parser.add_argument(
        "--huggingface-max-new-tokens",
        type=int,
        dest="huggingface_max_new_tokens",
        help="Maximum new tokens for local Hugging Face generation",
    )
    parser.add_argument(
        "--huggingface-cache-dir",
        help="Optional cache directory for downloaded Hugging Face models",
    )
    parser.add_argument(
        "--huggingface-trust-remote-code",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Allow custom model code when loading Hugging Face models",
    )
    parser.add_argument(
        "--llm-temperature",
        type=float,
        dest="llm_temperature",
        help="Sampling temperature for supported LLM providers",
    )
    parser.add_argument(
        "--decision-mode",
        choices=["strict", "triage"],
        help="Use strict keep-or-exclude or triage with maybe",
    )
    parser.add_argument(
        "--maybe-threshold-margin",
        type=float,
        dest="maybe_threshold_margin",
        help="Score margin below threshold that still counts as maybe in triage mode",
    )
    parser.add_argument(
        "--full-text-max-chars",
        type=int,
        dest="full_text_max_chars",
        help="Maximum number of full-text characters to include in screening",
    )
    parser.add_argument("--max-workers", type=int, help="Global parallel worker count used when stage-specific overrides are unset")
    parser.add_argument("--discovery-workers", type=int, help="Optional worker override for discovery sources")
    parser.add_argument("--io-workers", type=int, help="Optional worker override for PDF and full-text preparation stages")
    parser.add_argument("--screening-workers", type=int, help="Optional worker override for AI screening stages")
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        dest="request_timeout_seconds",
        help="HTTP timeout for API calls",
    )
    parser.add_argument(
        "--partial-rerun-mode",
        choices=["off", "reporting_only", "screening_and_reporting", "pdfs_screening_reporting"],
        help="Rerun only the affected downstream stages using already stored records",
    )
    parser.add_argument(
        "--incremental-report-regeneration",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Rewrite only the report artifacts whose contents changed",
    )
    parser.add_argument(
        "--enable-async-network-stages",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use an asyncio orchestration layer for network-heavy discovery and IO stages",
    )
    parser.add_argument(
        "--http-cache-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Persist eligible GET responses to the on-disk source-response cache",
    )
    parser.add_argument("--http-cache-dir", help="Directory for the persistent HTTP source-response cache")
    parser.add_argument(
        "--http-cache-ttl-seconds",
        type=int,
        dest="http_cache_ttl_seconds",
        help="Maximum age for cached GET responses before they are treated as stale",
    )
    parser.add_argument(
        "--http-retry-max-attempts",
        type=int,
        dest="http_retry_max_attempts",
        help="Maximum attempts for 429-aware request retries",
    )
    parser.add_argument(
        "--http-retry-base-delay-seconds",
        type=float,
        dest="http_retry_base_delay_seconds",
        help="Base exponential backoff delay used when a 429 response has no Retry-After header",
    )
    parser.add_argument(
        "--http-retry-max-delay-seconds",
        type=float,
        dest="http_retry_max_delay_seconds",
        help="Upper bound for request backoff delays in seconds",
    )
    parser.add_argument(
        "--pdf-batch-size",
        type=int,
        dest="pdf_batch_size",
        help="Queue size for each PDF enrichment or download batch",
    )
    parser.add_argument(
        "--resume-mode",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Resume and skip already-screened papers for the same query",
    )
    parser.add_argument(
        "--reset-query-records",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Delete existing paper rows for the active query before the run starts",
    )
    parser.add_argument(
        "--clear-screening-cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Delete cached screening results for the current screening context before the run starts",
    )
    parser.add_argument(
        "--disable-progress-bars",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Disable tqdm progress bars",
    )
    parser.add_argument(
        "--title-similarity-threshold",
        type=float,
        dest="title_similarity_threshold",
        help="Deduplication similarity threshold between 0 and 1",
    )
    parser.add_argument(
        "--log-http-requests",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Log HTTP endpoints, methods, and response summaries in verbose and ultra-verbose modes",
    )
    parser.add_argument(
        "--log-http-payloads",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Log truncated HTTP request and response payloads in ultra-verbose mode",
    )
    parser.add_argument(
        "--log-llm-prompts",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Log truncated LLM prompt excerpts in ultra-verbose mode",
    )
    parser.add_argument(
        "--log-llm-responses",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Log truncated LLM response excerpts in ultra-verbose mode",
    )
    parser.add_argument(
        "--log-screening-decisions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Log per-paper screening outcomes in verbose and ultra-verbose modes",
    )
    parser.add_argument("--profile-name", help="Optional name used when saving or loading guided UI profiles")
    parser.add_argument(
        "--fixture-data",
        dest="fixture_data_path",
        help="Path to a local JSON fixture file for fast offline discovery tests",
    )
    parser.add_argument(
        "--manual-source-path",
        help="Path to a CSV or JSON export for manual metadata import",
    )
    parser.add_argument(
        "--google-scholar-import-path",
        help="Path to a CSV or JSON export manually exported from Google Scholar-compatible tools",
    )
    parser.add_argument(
        "--researchgate-import-path",
        help="Path to a CSV or JSON export manually exported from ResearchGate or a connected repository",
    )
    parser.add_argument("--data-dir", help="Directory for pipeline state and SQLite artifacts")
    parser.add_argument("--papers-dir", help="Directory for downloaded PDFs and extracted text assets")
    parser.add_argument(
        "--relevant-pdfs-dir",
        help="Directory where PDFs for relevant papers should be stored when pdf-download-mode is relevant_only",
    )
    parser.add_argument("--results-dir", help="Directory for CSV, JSON, Markdown, and SQLite result exports")
    parser.add_argument("--database-path", help="Path to the main SQLite database file")
    parser.add_argument("--log-file-path", help="Path to the persistent run log file written alongside console and GUI logs")
    parser.add_argument(
        "--output-csv",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write CSV exports",
    )
    parser.add_argument(
        "--output-json",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write JSON exports",
    )
    parser.add_argument(
        "--output-markdown",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write Markdown exports",
    )
    parser.add_argument(
        "--output-sqlite-exports",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write SQLite decision export databases",
    )
    return parser


def parse_analysis_pass(value: str) -> AnalysisPassConfig:
    """Parse a compact analysis-pass string from CLI, config files, or the GUI builder."""

    candidate = value.strip()
    if not candidate:
        raise ValueError("Analysis pass cannot be empty")

    if candidate.startswith("{"):
        parsed = json.loads(candidate)
        return AnalysisPassConfig(**parsed)

    if "|" in candidate:
        parts = [part.strip() for part in candidate.split("|")]
        if len(parts) < 5:
            raise ValueError(
                "Extended analysis pass format must use name|provider|threshold|decision_mode|margin"
                "[|model_name|min_input_score]"
            )
        name, provider, threshold, decision_mode, margin = parts[:5]
        model_name = parts[5] if len(parts) >= 6 and parts[5] else None
        min_input_score = float(parts[6]) if len(parts) >= 7 and parts[6] else None
        return AnalysisPassConfig(
            name=name,
            llm_provider=provider,  # type: ignore[arg-type]
            threshold=float(threshold),
            decision_mode=decision_mode,  # type: ignore[arg-type]
            maybe_threshold_margin=float(margin),
            model_name=model_name,
            min_input_score=min_input_score,
        )

    parts = [part.strip() for part in candidate.split(":")]
    if len(parts) < 3:
        raise ValueError("Analysis pass must use name:provider:threshold[:decision_mode[:margin]]")
    name, provider, threshold = parts[:3]
    decision_mode = parts[3] if len(parts) >= 4 and parts[3] else "strict"
    margin_value = float(parts[4]) if len(parts) >= 5 and parts[4] else 10.0
    return AnalysisPassConfig(
        name=name,
        llm_provider=provider,  # type: ignore[arg-type]
        threshold=float(threshold),
        decision_mode=decision_mode,  # type: ignore[arg-type]
        maybe_threshold_margin=margin_value,
    )



