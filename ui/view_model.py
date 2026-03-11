"""Mapping helpers between the Tkinter form state and the validated runtime config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import ResearchConfig, parse_analysis_pass

PROFILE_DIR = Path("configs/profiles")

MULTILINE_FIELD_DEFAULTS = {
    "research_topic": "AI-assisted literature review",
    "research_question": "",
    "review_objective": "",
    "search_keywords": "large language models, systematic review",
    "inclusion_criteria": "",
    "exclusion_criteria": "",
    "banned_topics": "",
    "excluded_title_terms": "correction; erratum; editorial; retraction",
    "analysis_passes": "",
}

SCALAR_FIELD_DEFAULTS: dict[str, Any] = {
    "boolean_operators": "AND",
    "pages_to_retrieve": 2,
    "results_per_page": 25,
    "discovery_strategy": "balanced",
    "year_range_start": 2018,
    "year_range_end": 2026,
    "max_discovered_records": "",
    "min_discovered_records": 0,
    "max_papers_to_analyze": 50,
    "relevance_threshold": 70.0,
    "pdf_download_mode": "all",
    "full_text_max_chars": 12000,
    "llm_provider": "auto",
    "decision_mode": "strict",
    "maybe_threshold_margin": 10.0,
    "run_mode": "analyze",
    "verbosity": "normal",
    "max_workers": 4,
    "discovery_workers": 0,
    "io_workers": 0,
    "screening_workers": 0,
    "request_timeout_seconds": 30,
    "partial_rerun_mode": "off",
    "http_cache_dir": "data/http_cache",
    "http_cache_ttl_seconds": 86400,
    "http_retry_max_attempts": 4,
    "http_retry_base_delay_seconds": 1.0,
    "http_retry_max_delay_seconds": 30.0,
    "pdf_batch_size": 10,
    "title_similarity_threshold": 0.92,
    "fixture_data_path": "",
    "manual_source_path": "",
    "google_scholar_import_path": "",
    "researchgate_import_path": "",
    "data_dir": "data",
    "papers_dir": "papers",
    "relevant_pdfs_dir": "",
    "results_dir": "results",
    "database_path": "data/literature_review.db",
    "profile_name": "",
    "semantic_scholar_api_key": "",
    "crossref_mailto": "",
    "unpaywall_email": "",
    "springer_api_key": "",
    "core_api_key": "",
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_model": "gpt-5.4",
    "gemini_api_key": "",
    "gemini_base_url": "https://generativelanguage.googleapis.com/v1beta",
    "gemini_model": "gemini-2.5-flash",
    "ollama_base_url": "http://localhost:11434/v1",
    "ollama_model": "qwen3:8b",
    "ollama_api_key": "ollama",
    "llm_temperature": 0.1,
    "openalex_calls_per_second": 5.0,
    "semantic_scholar_calls_per_second": 3.0,
    "crossref_calls_per_second": 2.5,
    "springer_calls_per_second": 1.0,
    "arxiv_calls_per_second": 0.34,
    "pubmed_calls_per_second": 3.0,
    "europe_pmc_calls_per_second": 2.0,
    "core_calls_per_second": 1.5,
    "unpaywall_calls_per_second": 2.0,
    "huggingface_model": "Qwen/Qwen3-14B",
    "huggingface_task": "text-generation",
    "huggingface_device": "auto",
    "huggingface_dtype": "auto",
    "huggingface_max_new_tokens": 700,
    "huggingface_cache_dir": "",
}

BOOLEAN_FIELD_DEFAULTS = {
    "citation_snowballing_enabled": True,
    "skip_discovery": False,
    "download_pdfs": False,
    "analyze_full_text": False,
    "output_csv": True,
    "output_json": True,
    "output_markdown": True,
    "output_sqlite_exports": True,
    "openalex_enabled": True,
    "semantic_scholar_enabled": True,
    "crossref_enabled": True,
    "springer_enabled": False,
    "arxiv_enabled": False,
    "include_pubmed": False,
    "europe_pmc_enabled": False,
    "core_enabled": False,
    "resume_mode": True,
    "reset_query_records": False,
    "clear_screening_cache": False,
    "incremental_report_regeneration": False,
    "enable_async_network_stages": False,
    "http_cache_enabled": True,
    "disable_progress_bars": False,
    "log_http_requests": True,
    "log_http_payloads": True,
    "log_llm_prompts": True,
    "log_llm_responses": True,
    "log_screening_decisions": True,
    "huggingface_trust_remote_code": False,
}


def default_form_values() -> dict[str, Any]:
    """Return the default flat UI state used by the Tkinter workbench."""

    return {
        **MULTILINE_FIELD_DEFAULTS,
        **SCALAR_FIELD_DEFAULTS,
        **BOOLEAN_FIELD_DEFAULTS,
    }


def _path_to_ui_value(value: str | Path | None) -> str:
    """Normalize path-like values into stable forward-slash strings for the UI."""

    if value in {"", None}:
        return ""
    return Path(value).as_posix()


def config_to_form_values(config: ResearchConfig) -> dict[str, Any]:
    """Flatten a validated config object into UI-friendly scalar values."""

    values = default_form_values()
    values.update(
        {
            "research_topic": config.research_topic,
            "research_question": config.research_question,
            "review_objective": config.review_objective,
            "search_keywords": ", ".join(config.search_keywords),
            "inclusion_criteria": "; ".join(config.inclusion_criteria),
            "exclusion_criteria": "; ".join(config.exclusion_criteria),
            "banned_topics": "; ".join(config.banned_topics),
            "excluded_title_terms": "; ".join(config.excluded_title_terms),
            "analysis_passes": "\n".join(
                "|".join(
                    [
                        analysis_pass.name,
                        analysis_pass.llm_provider,
                        str(analysis_pass.threshold),
                        analysis_pass.decision_mode,
                        str(analysis_pass.maybe_threshold_margin),
                        analysis_pass.model_name or "",
                        "" if analysis_pass.min_input_score is None else str(analysis_pass.min_input_score),
                    ]
                )
                for analysis_pass in config.analysis_passes
            ),
            "boolean_operators": config.boolean_operators or "",
            "pages_to_retrieve": config.pages_to_retrieve,
            "results_per_page": config.results_per_page,
            "discovery_strategy": config.discovery_strategy,
            "year_range_start": config.year_range_start,
            "year_range_end": config.year_range_end,
            "max_discovered_records": config.max_discovered_records or "",
            "min_discovered_records": config.min_discovered_records,
            "max_papers_to_analyze": config.max_papers_to_analyze,
            "skip_discovery": config.skip_discovery,
            "relevance_threshold": config.relevance_threshold,
            "pdf_download_mode": config.pdf_download_mode,
            "full_text_max_chars": config.full_text_max_chars,
            "llm_provider": config.llm_provider,
            "decision_mode": config.decision_mode,
            "maybe_threshold_margin": config.maybe_threshold_margin,
            "run_mode": config.run_mode,
            "verbosity": config.verbosity,
            "max_workers": config.max_workers,
            "discovery_workers": config.discovery_workers,
            "io_workers": config.io_workers,
            "screening_workers": config.screening_workers,
            "request_timeout_seconds": config.request_timeout_seconds,
            "partial_rerun_mode": config.partial_rerun_mode,
            "incremental_report_regeneration": config.incremental_report_regeneration,
            "enable_async_network_stages": config.enable_async_network_stages,
            "http_cache_enabled": config.http_cache_enabled,
            "http_cache_dir": _path_to_ui_value(config.http_cache_dir),
            "http_cache_ttl_seconds": config.http_cache_ttl_seconds,
            "http_retry_max_attempts": config.http_retry_max_attempts,
            "http_retry_base_delay_seconds": config.http_retry_base_delay_seconds,
            "http_retry_max_delay_seconds": config.http_retry_max_delay_seconds,
            "pdf_batch_size": config.pdf_batch_size,
            "title_similarity_threshold": config.title_similarity_threshold,
            "fixture_data_path": _path_to_ui_value(config.fixture_data_path),
            "manual_source_path": _path_to_ui_value(config.manual_source_path),
            "google_scholar_import_path": _path_to_ui_value(config.google_scholar_import_path),
            "researchgate_import_path": _path_to_ui_value(config.researchgate_import_path),
            "data_dir": _path_to_ui_value(config.data_dir),
            "papers_dir": _path_to_ui_value(config.papers_dir),
            "relevant_pdfs_dir": _path_to_ui_value(config.relevant_pdfs_dir),
            "results_dir": _path_to_ui_value(config.results_dir),
            "database_path": _path_to_ui_value(config.database_path),
            "profile_name": config.profile_name or "",
            "citation_snowballing_enabled": config.citation_snowballing_enabled,
            "download_pdfs": config.download_pdfs,
            "analyze_full_text": config.analyze_full_text,
            "output_csv": config.output_csv,
            "output_json": config.output_json,
            "output_markdown": config.output_markdown,
            "output_sqlite_exports": config.output_sqlite_exports,
            "openalex_enabled": config.openalex_enabled,
            "semantic_scholar_enabled": config.semantic_scholar_enabled,
            "crossref_enabled": config.crossref_enabled,
            "springer_enabled": config.springer_enabled,
            "arxiv_enabled": config.arxiv_enabled,
            "include_pubmed": bool(config.include_pubmed),
            "europe_pmc_enabled": config.europe_pmc_enabled,
            "core_enabled": config.core_enabled,
            "resume_mode": config.resume_mode,
            "reset_query_records": config.reset_query_records,
            "clear_screening_cache": config.clear_screening_cache,
            "disable_progress_bars": config.disable_progress_bars,
            "log_http_requests": config.log_http_requests,
            "log_http_payloads": config.log_http_payloads,
            "log_llm_prompts": config.log_llm_prompts,
            "log_llm_responses": config.log_llm_responses,
            "log_screening_decisions": config.log_screening_decisions,
            "semantic_scholar_api_key": config.api_settings.semantic_scholar_api_key or "",
            "crossref_mailto": config.api_settings.crossref_mailto or "",
            "unpaywall_email": config.api_settings.unpaywall_email or "",
            "springer_api_key": config.api_settings.springer_api_key or "",
            "core_api_key": config.api_settings.core_api_key or "",
            "openai_api_key": config.api_settings.openai_api_key or "",
            "openai_base_url": config.api_settings.openai_base_url,
            "openai_model": config.api_settings.openai_model,
            "gemini_api_key": config.api_settings.gemini_api_key or "",
            "gemini_base_url": config.api_settings.gemini_base_url,
            "gemini_model": config.api_settings.gemini_model,
            "ollama_base_url": config.api_settings.ollama_base_url,
            "ollama_model": config.api_settings.ollama_model,
            "ollama_api_key": config.api_settings.ollama_api_key,
            "llm_temperature": config.api_settings.llm_temperature,
            "openalex_calls_per_second": config.api_settings.openalex_calls_per_second,
            "semantic_scholar_calls_per_second": config.api_settings.semantic_scholar_calls_per_second,
            "crossref_calls_per_second": config.api_settings.crossref_calls_per_second,
            "springer_calls_per_second": config.api_settings.springer_calls_per_second,
            "arxiv_calls_per_second": config.api_settings.arxiv_calls_per_second,
            "pubmed_calls_per_second": config.api_settings.pubmed_calls_per_second,
            "europe_pmc_calls_per_second": config.api_settings.europe_pmc_calls_per_second,
            "core_calls_per_second": config.api_settings.core_calls_per_second,
            "unpaywall_calls_per_second": config.api_settings.unpaywall_calls_per_second,
            "huggingface_model": config.api_settings.huggingface_model,
            "huggingface_task": config.api_settings.huggingface_task,
            "huggingface_device": config.api_settings.huggingface_device,
            "huggingface_dtype": config.api_settings.huggingface_dtype,
            "huggingface_max_new_tokens": config.api_settings.huggingface_max_new_tokens,
            "huggingface_cache_dir": _path_to_ui_value(config.api_settings.huggingface_cache_dir),
            "huggingface_trust_remote_code": config.api_settings.huggingface_trust_remote_code,
        }
    )
    return values


def form_values_to_config(values: dict[str, Any]) -> ResearchConfig:
    """Build a validated config object from flat UI values."""

    def as_int(name: str, default: int | None = None) -> int | None:
        raw = values.get(name, default)
        if raw in {"", None}:
            return default
        return int(raw)

    def as_float(name: str, default: float) -> float:
        raw = values.get(name, default)
        if raw in {"", None}:
            return default
        return float(raw)

    def as_bool(name: str) -> bool:
        return bool(values.get(name, False))

    def as_path(name: str) -> str | None:
        raw = str(values.get(name, "") or "").strip()
        return raw or None

    analysis_passes = [
        parse_analysis_pass(line.strip())
        for line in str(values.get("analysis_passes", "") or "").splitlines()
        if line.strip()
    ]

    return ResearchConfig(
        research_topic=str(values.get("research_topic", "") or "").strip(),
        research_question=str(values.get("research_question", "") or "").strip(),
        review_objective=str(values.get("review_objective", "") or "").strip(),
        inclusion_criteria=str(values.get("inclusion_criteria", "") or ""),
        exclusion_criteria=str(values.get("exclusion_criteria", "") or ""),
        banned_topics=str(values.get("banned_topics", "") or ""),
        excluded_title_terms=str(values.get("excluded_title_terms", "") or ""),
        search_keywords=str(values.get("search_keywords", "") or ""),
        boolean_operators=str(values.get("boolean_operators", "") or "") or None,
        pages_to_retrieve=as_int("pages_to_retrieve", 2) or 2,
        results_per_page=as_int("results_per_page", 25) or 25,
        discovery_strategy=str(values.get("discovery_strategy", "balanced") or "balanced"),
        year_range_start=as_int("year_range_start", 2018) or 2018,
        year_range_end=as_int("year_range_end", 2026) or 2026,
        max_discovered_records=as_int("max_discovered_records"),
        min_discovered_records=as_int("min_discovered_records", 0) or 0,
        max_papers_to_analyze=as_int("max_papers_to_analyze", 50) or 50,
        skip_discovery=as_bool("skip_discovery"),
        citation_snowballing_enabled=as_bool("citation_snowballing_enabled"),
        relevance_threshold=as_float("relevance_threshold", 70.0),
        download_pdfs=as_bool("download_pdfs"),
        pdf_download_mode=str(values.get("pdf_download_mode", "all") or "all"),
        analyze_full_text=as_bool("analyze_full_text"),
        full_text_max_chars=as_int("full_text_max_chars", 12000) or 12000,
        llm_provider=str(values.get("llm_provider", "auto") or "auto"),
        decision_mode=str(values.get("decision_mode", "strict") or "strict"),
        maybe_threshold_margin=as_float("maybe_threshold_margin", 10.0),
        run_mode=str(values.get("run_mode", "analyze") or "analyze"),
        verbosity=str(values.get("verbosity", "normal") or "normal"),
        output_csv=as_bool("output_csv"),
        output_json=as_bool("output_json"),
        output_markdown=as_bool("output_markdown"),
        output_sqlite_exports=as_bool("output_sqlite_exports"),
        analysis_passes=analysis_passes,
        openalex_enabled=as_bool("openalex_enabled"),
        semantic_scholar_enabled=as_bool("semantic_scholar_enabled"),
        crossref_enabled=as_bool("crossref_enabled"),
        springer_enabled=as_bool("springer_enabled"),
        arxiv_enabled=as_bool("arxiv_enabled"),
        include_pubmed=as_bool("include_pubmed"),
        europe_pmc_enabled=as_bool("europe_pmc_enabled"),
        core_enabled=as_bool("core_enabled"),
        max_workers=as_int("max_workers", 4) or 4,
        discovery_workers=as_int("discovery_workers", 0) or 0,
        io_workers=as_int("io_workers", 0) or 0,
        screening_workers=as_int("screening_workers", 0) or 0,
        request_timeout_seconds=as_int("request_timeout_seconds", 30) or 30,
        partial_rerun_mode=str(values.get("partial_rerun_mode", "off") or "off"),
        incremental_report_regeneration=as_bool("incremental_report_regeneration"),
        enable_async_network_stages=as_bool("enable_async_network_stages"),
        http_cache_enabled=as_bool("http_cache_enabled"),
        http_cache_dir=values.get("http_cache_dir", "data/http_cache"),
        http_cache_ttl_seconds=as_int("http_cache_ttl_seconds", 86400) or 86400,
        http_retry_max_attempts=as_int("http_retry_max_attempts", 4) or 4,
        http_retry_base_delay_seconds=as_float("http_retry_base_delay_seconds", 1.0),
        http_retry_max_delay_seconds=as_float("http_retry_max_delay_seconds", 30.0),
        pdf_batch_size=as_int("pdf_batch_size", 10) or 10,
        resume_mode=as_bool("resume_mode"),
        reset_query_records=as_bool("reset_query_records"),
        clear_screening_cache=as_bool("clear_screening_cache"),
        disable_progress_bars=as_bool("disable_progress_bars"),
        title_similarity_threshold=as_float("title_similarity_threshold", 0.92),
        log_http_requests=as_bool("log_http_requests"),
        log_http_payloads=as_bool("log_http_payloads"),
        log_llm_prompts=as_bool("log_llm_prompts"),
        log_llm_responses=as_bool("log_llm_responses"),
        log_screening_decisions=as_bool("log_screening_decisions"),
        profile_name=str(values.get("profile_name", "") or "").strip() or None,
        fixture_data_path=as_path("fixture_data_path"),
        manual_source_path=as_path("manual_source_path"),
        google_scholar_import_path=as_path("google_scholar_import_path"),
        researchgate_import_path=as_path("researchgate_import_path"),
        data_dir=values.get("data_dir", "data"),
        papers_dir=values.get("papers_dir", "papers"),
        relevant_pdfs_dir=as_path("relevant_pdfs_dir"),
        results_dir=values.get("results_dir", "results"),
        database_path=values.get("database_path", "data/literature_review.db"),
        api_settings={
            "semantic_scholar_api_key": str(values.get("semantic_scholar_api_key", "") or "") or None,
            "crossref_mailto": str(values.get("crossref_mailto", "") or "") or None,
            "unpaywall_email": str(values.get("unpaywall_email", "") or "") or None,
            "springer_api_key": str(values.get("springer_api_key", "") or "") or None,
            "core_api_key": str(values.get("core_api_key", "") or "") or None,
            "openai_api_key": str(values.get("openai_api_key", "") or "") or None,
            "openai_base_url": str(values.get("openai_base_url", "") or "https://api.openai.com/v1"),
            "openai_model": str(values.get("openai_model", "") or "gpt-5.4"),
            "gemini_api_key": str(values.get("gemini_api_key", "") or "") or None,
            "gemini_base_url": str(values.get("gemini_base_url", "") or "https://generativelanguage.googleapis.com/v1beta"),
            "gemini_model": str(values.get("gemini_model", "") or "gemini-2.5-flash"),
            "ollama_base_url": str(values.get("ollama_base_url", "") or "http://localhost:11434/v1"),
            "ollama_model": str(values.get("ollama_model", "") or "qwen3:8b"),
            "ollama_api_key": str(values.get("ollama_api_key", "") or "ollama"),
            "llm_temperature": as_float("llm_temperature", 0.1),
            "openalex_calls_per_second": as_float("openalex_calls_per_second", 5.0),
            "semantic_scholar_calls_per_second": as_float("semantic_scholar_calls_per_second", 3.0),
            "crossref_calls_per_second": as_float("crossref_calls_per_second", 2.5),
            "springer_calls_per_second": as_float("springer_calls_per_second", 1.0),
            "arxiv_calls_per_second": as_float("arxiv_calls_per_second", 0.34),
            "pubmed_calls_per_second": as_float("pubmed_calls_per_second", 3.0),
            "europe_pmc_calls_per_second": as_float("europe_pmc_calls_per_second", 2.0),
            "core_calls_per_second": as_float("core_calls_per_second", 1.5),
            "unpaywall_calls_per_second": as_float("unpaywall_calls_per_second", 2.0),
            "huggingface_model": str(values.get("huggingface_model", "") or "Qwen/Qwen3-14B"),
            "huggingface_task": str(values.get("huggingface_task", "") or "text-generation"),
            "huggingface_device": str(values.get("huggingface_device", "") or "auto"),
            "huggingface_dtype": str(values.get("huggingface_dtype", "") or "auto"),
            "huggingface_max_new_tokens": as_int("huggingface_max_new_tokens", 700) or 700,
            "huggingface_cache_dir": str(values.get("huggingface_cache_dir", "") or "") or None,
            "huggingface_trust_remote_code": as_bool("huggingface_trust_remote_code"),
        },
    ).finalize()


def load_config_file(path: str | Path) -> dict[str, Any]:
    """Load a JSON config payload from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def config_payload_to_form_values(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a persisted JSON config payload into flat UI values."""

    config = ResearchConfig(**payload).finalize()
    return config_to_form_values(config)


class ProfileManager:
    """Persist guided UI profiles as JSON configs compatible with the CLI."""

    def __init__(self, profile_dir: Path = PROFILE_DIR) -> None:
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[str]:
        """Return the available saved profile names without file extensions."""

        return sorted(path.stem for path in self.profile_dir.glob("*.json"))

    def save_profile(self, name: str, values: dict[str, Any]) -> Path:
        """Validate and persist the current UI state as a reusable JSON profile."""

        config = form_values_to_config(values)
        path = self.profile_dir / f"{name}.json"
        path.write_text(json.dumps(config.model_dump(mode="json"), indent=2), encoding="utf-8")
        return path

    def load_profile(self, name: str) -> dict[str, Any]:
        """Load a named JSON profile and convert it back into flat UI values."""

        payload = load_config_file(self.profile_dir / f"{name}.json")
        config = ResearchConfig(**payload).finalize()
        return config_to_form_values(config)
