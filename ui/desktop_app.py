"""Tkinter workbench for guided configuration, live logs, and result inspection."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import textwrap
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

import pandas as pd

from config import parse_analysis_pass
from pipeline.pipeline_controller import PipelineController
from ui.view_model import (
    BOOLEAN_FIELD_DEFAULTS,
    ProfileManager,
    SCALAR_FIELD_DEFAULTS,
    config_payload_to_form_values,
    default_form_values,
    form_values_to_config,
    load_config_file,
)

LOGGER = logging.getLogger(__name__)


class UILogHandler(logging.Handler):
    """Forward log records from worker threads into the Tkinter event queue."""

    def __init__(self, message_queue: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self.message_queue = message_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.message_queue.put(("log", self.format(record)))


class HoverTooltip:
    """Show contextual hover help next to the cursor without stealing focus."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.window: tk.Toplevel | None = None
        self.label: ttk.Label | None = None

    def show(self, text: str, *, x: int, y: int) -> None:
        """Render or update the hover tooltip with wrapped explanatory text."""

        message = textwrap.fill(text, width=72)
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.withdraw()
            self.window.overrideredirect(True)
            try:
                self.window.attributes("-topmost", True)
            except tk.TclError:
                # Some Tk builds do not expose every window manager attribute.
                pass
            frame = ttk.Frame(self.window, padding=8, relief="solid", borderwidth=1)
            frame.pack(fill="both", expand=True)
            self.label = ttk.Label(frame, justify="left", wraplength=480)
            self.label.pack(fill="both", expand=True)
        if self.label is not None:
            self.label.configure(text=message)
        x_pos = self._coerce_coordinate(x, self.root.winfo_pointerx())
        y_pos = self._coerce_coordinate(y, self.root.winfo_pointery())
        self.window.geometry(f"+{x_pos + 16}+{y_pos + 16}")
        self.window.deiconify()

    def hide(self) -> None:
        """Hide the tooltip until the next hover event."""

        if self.window is not None:
            self.window.withdraw()

    def _coerce_coordinate(self, value: Any, fallback: int) -> int:
        """Convert Tk event coordinates into integers, tolerating FocusIn placeholders like '??'."""

        try:
            return int(value)
        except (TypeError, ValueError):
            return int(fallback)


class DesktopWorkbench:
    """Tkinter workbench for guided configuration and result inspection."""

    SETTINGS_PAGES = [
        ("Review Setup", ["Review Brief"]),
        ("Discovery", ["Discovery"]),
        ("AI Screening", ["Screening and Models"]),
        ("Storage and Output", ["PDFs and Outputs"]),
        ("Runtime and Logs", ["Execution and Logging"]),
    ]

    MULTILINE_FIELDS = {
        "research_topic": ("Research brief", 3),
        "research_question": ("Research question", 3),
        "review_objective": ("Review objective", 3),
        "search_keywords": ("Search keywords (comma-separated)", 3),
        "inclusion_criteria": ("Inclusion criteria (; separated)", 3),
        "exclusion_criteria": ("Exclusion criteria (; separated)", 3),
        "banned_topics": ("Banned topics (; separated)", 2),
        "excluded_title_terms": ("Excluded title terms (; separated)", 2),
        "analysis_passes": ("Analysis passes / chained models", 4),
    }

    RADIO_FIELDS = {
        "boolean_operators": ["AND", "OR", "NOT"],
        "discovery_strategy": ["precise", "balanced", "broad"],
        "pdf_download_mode": ["all", "relevant_only"],
        "decision_mode": ["strict", "triage"],
        "run_mode": ["collect", "analyze"],
        "verbosity": ["quiet", "normal", "verbose", "debug"],
    }

    COMBOBOX_FIELDS = {
        "llm_provider": ["auto", "heuristic", "openai_compatible", "gemini", "ollama", "huggingface_local"],
        "openai_model": ["gpt-5.4"],
        "gemini_model": ["gemini-2.5-flash", "gemini-2.5-pro"],
        "ollama_model": ["qwen3:8b", "gpt-oss:20b"],
        "huggingface_model": ["Qwen/Qwen3-14B", "openai/gpt-oss-20b"],
        "huggingface_task": ["text-generation"],
        "huggingface_device": ["auto", "cpu", "cuda"],
        "huggingface_dtype": ["auto", "float16", "bfloat16", "float32"],
    }

    SPINBOX_FIELDS = {
        "pages_to_retrieve": {"from_": 1, "to": 50, "increment": 1},
        "results_per_page": {"from_": 1, "to": 200, "increment": 1},
        "year_range_start": {"from_": 1900, "to": 2100, "increment": 1},
        "year_range_end": {"from_": 1900, "to": 2100, "increment": 1},
        "min_discovered_records": {"from_": 0, "to": 10000, "increment": 1},
        "max_papers_to_analyze": {"from_": 1, "to": 10000, "increment": 1},
        "full_text_max_chars": {"from_": 500, "to": 200000, "increment": 500},
        "max_workers": {"from_": 1, "to": 64, "increment": 1},
        "request_timeout_seconds": {"from_": 1, "to": 600, "increment": 1},
        "huggingface_max_new_tokens": {"from_": 16, "to": 4096, "increment": 16},
    }

    SECRET_FIELDS = {
        "openai_api_key",
        "gemini_api_key",
        "ollama_api_key",
        "springer_api_key",
        "semantic_scholar_api_key",
    }

    GROUPS = [
        (
            "Review Brief",
            [
                "research_topic",
                "research_question",
                "review_objective",
                "search_keywords",
                "inclusion_criteria",
                "exclusion_criteria",
                "banned_topics",
                "excluded_title_terms",
            ],
        ),
        (
            "Discovery",
            [
                "boolean_operators",
                "discovery_strategy",
                "pages_to_retrieve",
                "results_per_page",
                "max_discovered_records",
                "min_discovered_records",
                "year_range_start",
                "year_range_end",
                "max_papers_to_analyze",
                "skip_discovery",
                "citation_snowballing_enabled",
                "openalex_enabled",
                "semantic_scholar_enabled",
                "crossref_enabled",
                "springer_enabled",
                "arxiv_enabled",
                "include_pubmed",
                "fixture_data_path",
                "manual_source_path",
                "google_scholar_import_path",
                "researchgate_import_path",
            ],
        ),
        (
            "Screening and Models",
            [
                "llm_provider",
                "analysis_passes",
                "relevance_threshold",
                "decision_mode",
                "maybe_threshold_margin",
                "analyze_full_text",
                "full_text_max_chars",
                "openai_base_url",
                "openai_model",
                "openai_api_key",
                "gemini_base_url",
                "gemini_model",
                "gemini_api_key",
                "ollama_base_url",
                "ollama_model",
                "ollama_api_key",
                "llm_temperature",
                "huggingface_model",
                "huggingface_task",
                "huggingface_device",
                "huggingface_dtype",
                "huggingface_max_new_tokens",
                "huggingface_cache_dir",
                "huggingface_trust_remote_code",
                "semantic_scholar_api_key",
                "springer_api_key",
            ],
        ),
        (
            "PDFs and Outputs",
            [
                "download_pdfs",
                "pdf_download_mode",
                "output_csv",
                "output_json",
                "output_markdown",
                "output_sqlite_exports",
                "data_dir",
                "papers_dir",
                "relevant_pdfs_dir",
                "results_dir",
                "database_path",
                "profile_name",
            ],
        ),
        (
            "Execution and Logging",
            [
                "run_mode",
                "verbosity",
                "max_workers",
                "request_timeout_seconds",
                "resume_mode",
                "disable_progress_bars",
                "title_similarity_threshold",
                "log_http_requests",
                "log_http_payloads",
                "log_llm_prompts",
                "log_llm_responses",
                "log_screening_decisions",
                "crossref_mailto",
                "unpaywall_email",
            ],
        ),
    ]

    LABELS = {
        "boolean_operators": "Boolean operators",
        "discovery_strategy": "Discovery strategy",
        "citation_snowballing_enabled": "Enable citation snowballing",
        "openalex_enabled": "Use OpenAlex",
        "semantic_scholar_enabled": "Use Semantic Scholar",
        "crossref_enabled": "Use Crossref",
        "springer_enabled": "Use Springer Nature API",
        "arxiv_enabled": "Use arXiv",
        "include_pubmed": "Use PubMed",
        "fixture_data_path": "Offline fixture file",
        "manual_source_path": "Manual import file",
        "google_scholar_import_path": "Google Scholar import file",
        "researchgate_import_path": "ResearchGate import file",
        "pages_to_retrieve": "Pages per source",
        "results_per_page": "Results per page",
        "max_discovered_records": "Max discovered records",
        "min_discovered_records": "Min discovered records",
        "year_range_start": "Year start",
        "year_range_end": "Year end",
        "max_papers_to_analyze": "Max papers to analyze",
        "skip_discovery": "Skip discovery",
        "relevance_threshold": "Relevance threshold",
        "llm_provider": "LLM provider",
        "decision_mode": "Decision mode",
        "maybe_threshold_margin": "Maybe margin",
        "analyze_full_text": "Analyze PDF full text",
        "full_text_max_chars": "Full-text chars",
        "request_timeout_seconds": "Request timeout (s)",
        "title_similarity_threshold": "Title similarity threshold",
        "openai_base_url": "OpenAI base URL",
        "openai_model": "OpenAI model",
        "openai_api_key": "OpenAI API key",
        "gemini_base_url": "Gemini base URL",
        "gemini_model": "Gemini model",
        "gemini_api_key": "Gemini API key",
        "ollama_base_url": "Ollama base URL",
        "ollama_model": "Ollama model",
        "ollama_api_key": "Ollama API key",
        "llm_temperature": "LLM temperature",
        "huggingface_model": "HF model",
        "huggingface_task": "HF task",
        "huggingface_device": "HF device",
        "huggingface_dtype": "HF dtype",
        "huggingface_max_new_tokens": "HF max new tokens",
        "huggingface_cache_dir": "HF cache dir",
        "semantic_scholar_api_key": "Semantic Scholar API key",
        "springer_api_key": "Springer API key",
        "crossref_mailto": "Crossref mailto",
        "unpaywall_email": "Unpaywall email",
        "download_pdfs": "Download paper PDFs",
        "pdf_download_mode": "PDF download mode",
        "output_csv": "Write CSV exports",
        "output_json": "Write JSON exports",
        "output_markdown": "Write Markdown summary",
        "output_sqlite_exports": "Write SQLite exports",
        "data_dir": "Data directory",
        "papers_dir": "PDF storage directory",
        "relevant_pdfs_dir": "Relevant PDF directory",
        "results_dir": "Results directory",
        "database_path": "Main SQLite database path",
        "profile_name": "Profile name",
        "run_mode": "Run mode",
        "verbosity": "Verbosity level",
        "max_workers": "Parallel workers",
        "resume_mode": "Resume previous screening",
        "disable_progress_bars": "Disable progress bars",
        "log_http_requests": "Log HTTP requests",
        "log_http_payloads": "Log HTTP payloads",
        "log_llm_prompts": "Log LLM prompts",
        "log_llm_responses": "Log LLM responses",
        "log_screening_decisions": "Log screening decisions",
        "huggingface_trust_remote_code": "Trust HF remote code",
    }

    PATH_FIELD_MODES = {
        "fixture_data_path": "file",
        "manual_source_path": "file",
        "google_scholar_import_path": "file",
        "researchgate_import_path": "file",
        "database_path": "save_file",
        "data_dir": "directory",
        "papers_dir": "directory",
        "relevant_pdfs_dir": "directory",
        "results_dir": "directory",
        "huggingface_cache_dir": "directory",
    }

    SLIDER_FIELDS = {
        "relevance_threshold": {"from_": 0.0, "to": 100.0, "resolution": 1.0, "digits": 0},
        "maybe_threshold_margin": {"from_": 0.0, "to": 100.0, "resolution": 1.0, "digits": 0},
        "llm_temperature": {"from_": 0.0, "to": 1.5, "resolution": 0.05, "digits": 2},
        "title_similarity_threshold": {"from_": 0.0, "to": 1.0, "resolution": 0.01, "digits": 2},
    }

    HANDBOOK_GUIDES = {
        "guide:outputs": (
            "Guide",
            "Where CSV, JSON, SQLite, and PDFs go",
            "Use the 'PDFs and Outputs' section in Settings. There you can turn CSV, JSON, Markdown, and SQLite "
            "exports on or off, choose whether PDFs should be downloaded, and set the data, papers, results, "
            "database, and relevant-PDF directories. If you only want PDFs for accepted papers, enable "
            "'Download PDFs' and set 'PDF download mode' to 'relevant_only'. The most-used copies of these controls "
            "also appear at the top of the Settings tab under 'Most-Used Controls'.",
        ),
        "guide:models": (
            "Guide",
            "How to choose the AI model",
            "Use the 'Screening and Models' section. 'LLM provider' decides whether the run uses heuristic scoring, "
            "OpenAI-compatible APIs, Gemini, Ollama, or a local Hugging Face model. Then configure the matching model "
            "fields such as OpenAI model, Gemini model, Ollama model, or HF model. Thresholds and decision mode in "
            "the same section control how strict the keep/exclude decisions are. If you need multiple models in sequence, use "
            "'Edit Passes' to build a pass chain with per-pass thresholds, model overrides, and entry-score gates. "
            "The most-used model controls also appear at the top of Settings under 'Most-Used Controls'.",
        ),
        "guide:api_keys": (
            "Guide",
            "Where API keys and endpoint settings go",
            "Provider keys and endpoint URLs live in 'Screening and Models' and 'Execution and Logging'. "
            "OpenAI-compatible keys, Gemini base URL and API key, Ollama base URL and API key, Semantic Scholar API key, "
            "Springer API key, Crossref mailto, and Unpaywall email are all editable in the GUI and saved into profiles.",
        ),
        "guide:verbose": (
            "Guide",
            "How to make the run fully verbose",
            "Use the 'Execution and Logging' section. Set 'Verbosity' to 'verbose' or 'debug', and keep the logging "
            "toggles enabled for HTTP requests, payloads, LLM prompts, LLM responses, and screening decisions. "
            "Verbose is good for normal auditing. Debug adds truncated payload and prompt details.",
        ),
        "guide:rate_limits": (
            "Guide",
            "Why Semantic Scholar shows 429 rate limits",
            "A 429 means the remote API refused additional requests for a while. That is usually a provider-side "
            "limit, not a crash in your pipeline. To reduce pressure, lower pages per source or results per page, "
            "disable the source temporarily, or supply a provider API key when supported.",
        ),
        "guide:actions": (
            "Guide",
            "What Start Run, Analyze Stored Results, and Force Stop do",
            "Start Run follows the current settings as shown in the form. Analyze Stored Results skips new discovery "
            "for this run and jumps directly into analysis using already stored records for the current query. "
            "Force Stop requests a controlled shutdown of the running pipeline and cancels queued work where possible.",
        ),
    }

    SECTION_HELP_TEXTS = {
        "Review Brief": (
            "Define the review context the screener should use. This brief shapes query expansion, "
            "screening decisions, and the final explanation for why a paper was kept or excluded."
        ),
        "Discovery": (
            "Control where papers are discovered and how broad the search becomes. These settings "
            "affect recall, API volume, rate limits, and when discovery stops."
        ),
        "Screening and Models": (
            "Choose how papers are evaluated after discovery. This section controls the LLM or "
            "heuristic screener, thresholds, full-text use, and provider-specific model settings."
        ),
        "PDFs and Outputs": (
            "Choose which artifacts are written to disk and where they go. Relevant PDFs can be "
            "downloaded automatically into a dedicated folder after screening."
        ),
        "Execution and Logging": (
            "Tune runtime behavior, concurrency, resumability, and how much internal detail is shown "
            "in the log window. Verbose and debug expose more API and screening activity."
        ),
    }

    FIELD_HELP_TEXTS = {
        "research_topic": "Summarize the topic, scope, and intended use of the review in plain language.",
        "research_question": (
            "State the main research question the pipeline should optimize for when judging paper relevance."
        ),
        "review_objective": (
            "Describe the concrete goal of the review, such as benchmarking, mapping the state of the art, "
            "or identifying methods for a thesis chapter."
        ),
        "search_keywords": (
            "Comma-separated discovery terms. The pipeline combines these with the topic and boolean operators "
            "to build source queries."
        ),
        "inclusion_criteria": (
            "Semicolon-separated rules that make a paper eligible, for example specific methods, populations, "
            "domains, or publication types."
        ),
        "exclusion_criteria": (
            "Semicolon-separated rules for excluding papers, such as editorials, non-peer-reviewed work, "
            "or unrelated domains."
        ),
        "banned_topics": (
            "Hard-stop topics that should never be retained even if keyword overlap is high. Matches are "
            "logged as explicit exclusion reasons."
        ),
        "excluded_title_terms": (
            "Semicolon-separated title terms that should be filtered out early, such as correction, retraction, "
            "editorial, or commentary."
        ),
        "boolean_operators": (
            "Default boolean operator used when composing keyword queries. AND narrows recall, OR broadens it, "
            "and NOT should be used carefully because it can hide relevant studies."
        ),
        "discovery_strategy": (
            "Precise keeps the query tight, balanced is the default middle ground, and broad expands query "
            "variants to maximize recall across sources."
        ),
        "pages_to_retrieve": (
            "How many result pages to request per enabled source before discovery stops or global caps are reached."
        ),
        "results_per_page": "Batch size requested from each source API on every discovery page.",
        "max_discovered_records": (
            "Hard cap on the unique deduplicated records collected during discovery. Once reached, discovery ends."
        ),
        "min_discovered_records": (
            "Minimum number of unique records required after merge and deduplication. If the run finds fewer, "
            "it stops before screening so you can broaden the search."
        ),
        "year_range_start": "Lower publication year bound applied during discovery when the source supports it.",
        "year_range_end": "Upper publication year bound applied during discovery when the source supports it.",
        "max_papers_to_analyze": (
            "Limit on how many discovered papers move on to screening. Useful when discovery is broad but you want "
            "to cap LLM cost or runtime."
        ),
        "skip_discovery": (
            "Skip new discovery API calls for this run and continue from records already stored in SQLite for the "
            "current query. This is useful when you want to re-run screening or reporting without searching again."
        ),
        "citation_snowballing_enabled": (
            "Enable backward and forward citation expansion after initial discovery. This can improve recall but "
            "adds more API calls and follow-up papers."
        ),
        "openalex_enabled": (
            "Search OpenAlex for broad scholarly metadata, abstracts, concepts, and citation links. It is one of the "
            "best default discovery sources for systematic review recall."
        ),
        "semantic_scholar_enabled": (
            "Search Semantic Scholar for metadata, abstracts, references, and citation context. It is useful for "
            "ranking and snowballing, but public access can be rate-limited."
        ),
        "crossref_enabled": (
            "Search Crossref's DOI registry. It is excellent for normalized metadata and DOI recovery, but abstracts "
            "and citation details are often less complete than OpenAlex or Semantic Scholar."
        ),
        "springer_enabled": (
            "Query Springer Nature's API for publisher-hosted metadata and links. This is especially useful when you "
            "want Springer content directly, but it typically benefits from an API key."
        ),
        "arxiv_enabled": (
            "Include arXiv preprints. This improves recall for AI and machine-learning topics, especially for very "
            "recent work that may not yet be indexed elsewhere."
        ),
        "include_pubmed": (
            "Include PubMed for biomedical or clinical topics. It is usually not necessary for general AI reviews "
            "unless the question touches medicine, health, or life sciences."
        ),
        "fixture_data_path": (
            "Optional offline fixture file for deterministic testing. Use this when you want to validate the pipeline "
            "without live API calls."
        ),
        "manual_source_path": (
            "Optional path to manually supplied CSV or JSON discovery records. This is useful for custom exports or "
            "sources that do not provide a supported live API."
        ),
        "google_scholar_import_path": (
            "Path to a manual Google Scholar export or prepared CSV/JSON import. The UI does not perform live Scholar "
            "scraping; this setting lets you merge exported records safely."
        ),
        "researchgate_import_path": (
            "Path to a manual ResearchGate export or prepared CSV/JSON import. This is intended for imported records, "
            "not live ResearchGate scraping."
        ),
        "llm_provider": (
            "Choose how papers are screened. Auto prefers configured LLMs when available, heuristic is local scoring "
            "without a model, and the other options pin the run to a specific provider."
        ),
        "analysis_passes": (
            "Optional multi-pass screening plan. This lets you chain multiple models or providers in sequence, each "
            "with its own threshold, decision mode, optional model override, and optional minimum previous-pass score. "
            "Use the pass builder button in the GUI for the easiest setup."
        ),
        "openai_model": (
            "Model name used when the provider is OpenAI-compatible. Set this to the hosted model you want, for example "
            "gpt-5.4, and pair it with the matching API key and base URL."
        ),
        "ollama_model": (
            "Model tag used for Ollama runs, for example qwen3:8b or gpt-oss:20b. This is the local model that Ollama "
            "will execute when a pass uses the Ollama provider."
        ),
        "huggingface_model": (
            "Local Hugging Face model used for screening. The default Qwen/Qwen3-14B is the balanced local choice for "
            "this project, but you can replace it with any compatible instruct model."
        ),
        "relevance_threshold": (
            "Final score threshold for keeping a paper. For example, 85 means only strong matches should be retained."
        ),
        "decision_mode": (
            "Strict keeps only papers that clearly meet the threshold, while triage keeps maybes in play for later review."
        ),
        "maybe_threshold_margin": (
            "Margin below the main threshold that still counts as maybe. A larger margin creates a wider review shortlist."
        ),
        "analyze_full_text": (
            "If enabled, the screener uses extracted PDF text in addition to title and abstract when full text is available."
        ),
        "full_text_max_chars": (
            "Maximum number of extracted full-text characters sent into screening. This protects runtime and prompt size."
        ),
        "openai_base_url": (
            "Base URL for OpenAI or an OpenAI-compatible endpoint. Leave the default for OpenAI, or point it to a "
            "compatible hosted gateway."
        ),
        "gemini_base_url": (
            "Base URL for the Gemini Generative Language API. The default points to Google's hosted Gemini endpoint."
        ),
        "gemini_model": (
            "Gemini model name used when the Gemini provider is selected, for example gemini-2.5-flash or gemini-2.5-pro."
        ),
        "gemini_api_key": (
            "Credential for the Gemini provider. It is masked in the UI and sent only to the configured Gemini endpoint."
        ),
        "openai_api_key": "Credential for the OpenAI-compatible provider. It is masked in the UI and never logged verbatim.",
        "ollama_base_url": "Local or remote Ollama server URL, usually http://localhost:11434.",
        "ollama_api_key": "Optional Ollama gateway key if your endpoint requires authentication.",
        "llm_temperature": (
            "Sampling temperature for supported LLM backends. Lower values are more deterministic, while higher values "
            "allow more variation in the screening explanation."
        ),
        "huggingface_task": "Transformers pipeline task used for the local Hugging Face model.",
        "huggingface_device": "Run the local model on auto selection, CPU, or CUDA if a GPU is available.",
        "huggingface_dtype": "Numerical precision for local Hugging Face inference. Lower precision can reduce memory use.",
        "huggingface_max_new_tokens": "Maximum tokens the local model may generate for one screening response.",
        "huggingface_cache_dir": "Optional local cache directory for downloaded Hugging Face model files.",
        "huggingface_trust_remote_code": (
            "Allow custom model code from Hugging Face repositories. Enable only when you trust the selected model."
        ),
        "semantic_scholar_api_key": "Optional Semantic Scholar API key for higher limits or authenticated access.",
        "springer_api_key": "API key for Springer Nature requests when you want live Springer discovery.",
        "download_pdfs": (
            "Download PDFs when open-access links are available. If disabled, the run keeps only metadata and screening output."
        ),
        "pdf_download_mode": (
            "All downloads PDFs for every discovered record with an open-access link. Relevant only delays downloads until "
            "a paper passes the screening thresholds."
        ),
        "database_path": (
            "Path to the main SQLite database that stores the discovered papers, screening cache, and decision history."
        ),
        "results_dir": (
            "Folder where papers.csv, included_papers.csv, excluded_papers.csv, JSON outputs, Markdown summaries, and "
            "decision export databases are written."
        ),
        "papers_dir": (
            "Base folder for downloaded paper PDFs and related extracted assets. If PDF download mode is 'all', files land here."
        ),
        "relevant_pdfs_dir": (
            "Folder for PDFs that passed the relevance threshold when 'PDF download mode' is set to 'relevant_only'. "
            "Use the same path as the main PDF folder if you want all PDFs kept together."
        ),
        "output_csv": "Write tabular review outputs such as papers.csv, included_papers.csv, and excluded_papers.csv.",
        "output_json": "Write machine-readable JSON outputs such as ranked results and PRISMA-style flow summaries.",
        "output_markdown": "Write the generated literature review summary and other Markdown reports.",
        "output_sqlite_exports": (
            "Write included and excluded export databases in addition to the main runtime SQLite database."
        ),
        "data_dir": "Base directory used for persistent runtime data such as SQLite files and cached artifacts.",
        "profile_name": "Name used when saving the current UI settings as a reusable profile.",
        "run_mode": (
            "Collect stops after discovery and persistence, while analyze continues through screening, ranking, and reporting."
        ),
        "verbosity": (
            "Quiet shows only important problems, normal shows stage progress, verbose adds source and finding details, "
            "and debug also includes truncated request and prompt diagnostics."
        ),
        "max_workers": "Maximum worker threads used for parallel API discovery and other concurrent tasks.",
        "request_timeout_seconds": "Network timeout applied to external API requests.",
        "resume_mode": (
            "Reuse prior database state so interrupted runs can continue instead of repeating already completed work."
        ),
        "disable_progress_bars": "Turn off progress bars when you prefer a cleaner console or log view.",
        "title_similarity_threshold": (
            "Similarity cutoff used for title-based deduplication when DOI matches are missing."
        ),
        "log_http_requests": (
            "Print request-level API activity in verbose/debug mode so you can see which sources and endpoints were called."
        ),
        "log_http_payloads": (
            "Include truncated request parameters and response snippets in debug mode. Secrets stay redacted."
        ),
        "log_llm_prompts": "Show truncated screening prompts in debug mode for audit and troubleshooting.",
        "log_llm_responses": "Show truncated model responses in debug mode so you can inspect screening behavior.",
        "log_screening_decisions": (
            "Log per-paper decisions, scores, and reasons during screening. Useful when tuning thresholds and criteria."
        ),
        "crossref_mailto": (
            "Contact email passed to Crossref requests. Supplying one is good API etiquette and can improve traceability."
        ),
        "unpaywall_email": (
            "Contact email required by Unpaywall when checking for open-access PDFs."
        ),
    }

    def __init__(self, args: Any) -> None:
        self.args = args
        self.root = tk.Tk()
        self.root.title("PRISMA Literature Review Workbench")
        self.root.geometry("1400x900")
        self.profile_manager = ProfileManager()
        self.message_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.run_thread: threading.Thread | None = None
        self.current_controller: PipelineController | None = None
        self.current_result: dict[str, Any] = {}
        self.log_handler = UILogHandler(self.message_queue)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        self.root_logger = logging.getLogger()
        self.root_logger.addHandler(self.log_handler)

        self.form_values = default_form_values()
        if getattr(args, "config_file", None):
            payload = load_config_file(args.config_file)
            self.form_values = config_payload_to_form_values(payload)

        self.scalar_vars: dict[str, tk.Variable] = {}
        self.text_widgets: dict[str, tk.Text] = {}
        self.field_focus_widgets: dict[str, tk.Widget] = {}
        self.field_input_widgets: dict[str, tk.Widget] = {}
        self.field_widget_types: dict[str, str] = {}
        self.section_frames: dict[str, ttk.LabelFrame] = {}
        self.field_to_settings_page: dict[str, str] = {}
        self.treeviews: dict[str, ttk.Treeview] = {}
        self.table_frames: dict[str, ttk.Frame] = {}
        self.outputs_tree: ttk.Treeview | None = None
        self.handbook_tree: ttk.Treeview | None = None
        self.handbook_text: scrolledtext.ScrolledText | None = None
        self.settings_pages_notebook: ttk.Notebook | None = None
        self.settings_page_frames: dict[str, ttk.Frame] = {}
        self.settings_search_choice_var = tk.StringVar(value="")
        self.settings_search_var = tk.StringVar(value="")
        self.settings_search_combo: ttk.Combobox | None = None
        self.model_summary_text: scrolledtext.ScrolledText | None = None
        self.output_summary_text: scrolledtext.ScrolledText | None = None
        self.slider_value_labels: dict[str, ttk.Label] = {}
        self.base_status_message = "Ready."
        self.status_var = tk.StringVar(value=self.base_status_message)
        self.hover_help_enabled = tk.BooleanVar(value=True)
        self.hover_tooltip = HoverTooltip(self.root)
        self._hover_message_active = False
        self.all_filter_var = tk.StringVar(value="all")
        self.all_search_var = tk.StringVar(value="")
        self.handbook_search_var = tk.StringVar(value="")
        self.handbook_entries = self._build_handbook_entries()

        self._build_layout()
        self._apply_form_values(self.form_values)
        self._register_settings_observers()
        self._refresh_settings_search_results()
        self._refresh_settings_overview()
        self._refresh_profile_choices()
        self.root.after(100, self._poll_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> int:
        """Enter the Tk event loop until the user closes the application window."""

        self.root.mainloop()
        return 0

    def _build_layout(self) -> None:
        """Construct the top-level toolbar, notebook, and status bar widgets."""

        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")
        start_button = ttk.Button(toolbar, text="Start Run", command=self._start_run)
        start_button.pack(side="left", padx=4)
        analyze_button = ttk.Button(
            toolbar,
            text="Analyze Stored Results",
            command=lambda: self._start_run(skip_discovery_override=True, run_mode_override="analyze"),
        )
        analyze_button.pack(side="left", padx=4)
        force_stop_button = ttk.Button(toolbar, text="Force Stop", command=self._force_stop)
        force_stop_button.pack(side="left", padx=4)
        load_config_button = ttk.Button(toolbar, text="Load Config", command=self._load_config_file)
        load_config_button.pack(side="left", padx=4)
        save_profile_button = ttk.Button(toolbar, text="Save Profile", command=self._save_profile)
        save_profile_button.pack(side="left", padx=4)
        load_profile_button = ttk.Button(toolbar, text="Load Profile", command=self._load_profile)
        load_profile_button.pack(side="left", padx=4)
        refresh_button = ttk.Button(toolbar, text="Refresh Results", command=self._refresh_results_from_disk)
        refresh_button.pack(side="left", padx=4)
        open_results_button = ttk.Button(toolbar, text="Open Results Folder", command=self._open_results_dir)
        open_results_button.pack(side="left", padx=4)
        ttk.Checkbutton(
            toolbar,
            text="Hover Help",
            variable=self.hover_help_enabled,
            command=self._toggle_hover_help,
        ).pack(side="right", padx=4)
        self._bind_hover_help(start_button, "Run the full pipeline using the current UI settings.")
        self._bind_hover_help(
            analyze_button,
            "Skip new discovery for this run and go directly into AI analysis using already stored records.",
        )
        self._bind_hover_help(
            force_stop_button,
            "Request a controlled stop for the current run. Running requests may need a moment to finish.",
        )
        self._bind_hover_help(load_config_button, "Load a saved JSON config file into the UI.")
        self._bind_hover_help(save_profile_button, "Save the current UI settings as a reusable profile.")
        self._bind_hover_help(load_profile_button, "Load a saved UI profile.")
        self._bind_hover_help(refresh_button, "Reload result files from disk without starting a new run.")
        self._bind_hover_help(open_results_button, "Open the configured results directory in the file manager.")

        ttk.Label(toolbar, text="Profile:").pack(side="left", padx=(16, 4))
        self.profile_combo = ttk.Combobox(toolbar, width=30, state="readonly")
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_profile())

        status_bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=8)
        status_bar.pack(fill="x", side="bottom")

        notebook = ttk.Notebook(self.root)
        self.notebook = notebook
        notebook.pack(fill="both", expand=True)

        self.settings_tab = ttk.Frame(notebook)
        self.handbook_tab = ttk.Frame(notebook)
        self.log_tab = ttk.Frame(notebook)
        self.all_tab = ttk.Frame(notebook)
        self.included_tab = ttk.Frame(notebook)
        self.excluded_tab = ttk.Frame(notebook)
        self.outputs_tab = ttk.Frame(notebook)
        notebook.add(self.settings_tab, text="Settings")
        notebook.add(self.handbook_tab, text="Handbook")
        notebook.add(self.log_tab, text="Run Log")
        notebook.add(self.all_tab, text="All Papers")
        notebook.add(self.included_tab, text="Included")
        notebook.add(self.excluded_tab, text="Excluded")
        notebook.add(self.outputs_tab, text="Outputs")

        self._build_settings_tab()
        self._build_handbook_tab()
        self._build_log_tab()
        self._build_table_tab(self.all_tab, "all_papers", include_filters=True)
        self._build_table_tab(self.included_tab, "included_papers")
        self._build_table_tab(self.excluded_tab, "excluded_papers")
        self._build_outputs_tab()

    def _build_settings_tab(self) -> None:
        """Render the grouped configuration form used to build a `ResearchConfig`."""
        container = ttk.Frame(self.settings_tab, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(
            container,
            text=(
                "Every CLI-relevant runtime setting is exposed here. The settings are split into dedicated pages so "
                "you can work with actual GUI controls such as dropdowns, radio buttons, switches, sliders, and "
                "browse dialogs instead of hunting through one long text-heavy form."
            ),
            wraplength=1180,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        quick_access = ttk.LabelFrame(container, text="Quick Access", padding=10)
        quick_access.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        quick_access.columnconfigure(0, weight=1)
        quick_access.columnconfigure(1, weight=1)
        self._build_settings_quick_access(quick_access)

        page_notebook = ttk.Notebook(container)
        page_notebook.grid(row=2, column=0, sticky="nsew")
        self.settings_pages_notebook = page_notebook

        grouped_fields = {section_name: field_names for section_name, field_names in self.GROUPS}
        for page_name, section_names in self.SETTINGS_PAGES:
            page = ttk.Frame(page_notebook, padding=10)
            page.columnconfigure(0, weight=1)
            page_notebook.add(page, text=page_name)
            self.settings_page_frames[page_name] = page

            intro = ttk.Label(
                page,
                text=(
                    "Use the controls on this page to adjust the corresponding runtime behavior. Hover any field for a "
                    "plain-language explanation or open the Handbook tab for the full reference."
                ),
                wraplength=1120,
                justify="left",
            )
            intro.grid(row=0, column=0, sticky="w", pady=(0, 8))
            self._bind_hover_help(intro, f"Settings page: {page_name}.")

            for row, section_name in enumerate(section_names, start=1):
                self._render_settings_group(page, page_name, section_name, grouped_fields[section_name], row)

        self._populate_quick_access_controls()

    def _render_settings_group(
        self,
        parent: ttk.Frame,
        page_name: str,
        section_name: str,
        field_names: list[str],
        row: int,
    ) -> None:
        """Render one logical settings group inside the selected settings page."""

        frame = ttk.LabelFrame(parent, text=section_name, padding=10)
        frame.grid(row=row, column=0, sticky="ew", pady=6)
        frame.columnconfigure(1, weight=1)
        self.section_frames[section_name] = frame
        self._bind_hover_help(frame, self.SECTION_HELP_TEXTS.get(section_name, section_name))

        summary_label = ttk.Label(
            frame,
            text=self.SECTION_HELP_TEXTS.get(section_name, ""),
            wraplength=1040,
            justify="left",
        )
        summary_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 8))
        self._bind_hover_help(summary_label, self.SECTION_HELP_TEXTS.get(section_name, section_name))

        for index, field_name in enumerate(field_names, start=1):
            self.field_to_settings_page[field_name] = page_name
            self._render_field(frame, field_name, index)

    def _render_field(self, frame: ttk.LabelFrame, field_name: str, row: int) -> None:
        """Render one settings field using the most appropriate widget type."""

        label = self.LABELS.get(field_name, field_name.replace("_", " ").title())
        help_text = self._help_text_for_field(field_name)

        if field_name in self.MULTILINE_FIELDS:
            self._render_multiline_field(frame, field_name, label, help_text, row)
            return

        if field_name in BOOLEAN_FIELD_DEFAULTS:
            variable = tk.BooleanVar(value=BOOLEAN_FIELD_DEFAULTS[field_name])
            widget = ttk.Checkbutton(frame, text=label, variable=variable)
            widget.grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=4)
            self.scalar_vars[field_name] = variable
            self.field_input_widgets[field_name] = widget
            self.field_focus_widgets[field_name] = widget
            self.field_widget_types[field_name] = "checkbutton"
            self._bind_hover_help(widget, help_text)
            return

        label_widget = ttk.Label(frame, text=label)
        label_widget.grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        self._bind_hover_help(label_widget, help_text)

        if field_name in self.RADIO_FIELDS:
            self._render_radio_field(frame, field_name, help_text, row)
        elif field_name in self.SLIDER_FIELDS:
            self._render_slider_field(frame, field_name, help_text, row)
        elif field_name in self.COMBOBOX_FIELDS:
            self._render_combobox_field(frame, field_name, help_text, row)
        elif field_name in self.SPINBOX_FIELDS:
            self._render_spinbox_field(frame, field_name, help_text, row)
        elif field_name in self.PATH_FIELD_MODES:
            self._render_path_field(frame, field_name, help_text, row)
        else:
            self._render_entry_field(frame, field_name, help_text, row)

    def _render_multiline_field(
        self,
        frame: ttk.LabelFrame,
        field_name: str,
        label: str,
        help_text: str,
        row: int,
    ) -> None:
        """Render a free-form multi-line text field or the analysis-pass summary panel."""

        _, height = self.MULTILINE_FIELDS[field_name]
        label_widget = ttk.Label(frame, text=label)
        label_widget.grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        self._bind_hover_help(label_widget, help_text)

        container = ttk.Frame(frame)
        container.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        container.columnconfigure(0, weight=1)

        if field_name == "analysis_passes":
            widget = scrolledtext.ScrolledText(container, height=height, wrap="word", state="disabled")
            widget.grid(row=0, column=0, sticky="ew")
            helper = ttk.Label(
                container,
                text=(
                    "Use the visual pass-chain editor below to choose one or more models, thresholds, and entry-score "
                    "gates. This summary updates automatically."
                ),
                wraplength=760,
                justify="left",
            )
            helper.grid(row=1, column=0, sticky="w", pady=(6, 0))
            button_bar = ttk.Frame(container)
            button_bar.grid(row=2, column=0, sticky="w", pady=(6, 0))
            edit_button = ttk.Button(button_bar, text="Edit Passes", command=self._open_pass_builder)
            edit_button.pack(side="left")
            clear_button = ttk.Button(button_bar, text="Clear Passes", command=lambda: self._write_analysis_passes([]))
            clear_button.pack(side="left", padx=(6, 0))
            self._bind_hover_help(edit_button, "Open the visual editor for chained screening passes and model/provider selection.")
            self._bind_hover_help(clear_button, "Remove the current chained-pass definition and fall back to the main provider settings.")
            self._bind_hover_help(helper, help_text)
            widget.bind("<KeyRelease>", lambda _event: "break")
            self.field_widget_types[field_name] = "pass_builder"
        else:
            widget = tk.Text(container, height=height, wrap="word")
            widget.grid(row=0, column=0, sticky="ew")
            self.field_widget_types[field_name] = "multiline"

        self.text_widgets[field_name] = widget
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self._bind_hover_help(widget, help_text)

    def _render_radio_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render an enumerated field as a compact radio-button group."""

        variable = tk.StringVar(value=str(SCALAR_FIELD_DEFAULTS.get(field_name, "")))
        container = ttk.Frame(frame)
        container.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        for index, option in enumerate(self.RADIO_FIELDS[field_name]):
            button = ttk.Radiobutton(container, text=option, value=option, variable=variable)
            button.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 10), pady=2)
            self._bind_hover_help(button, help_text)
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = container
        self.field_focus_widgets[field_name] = container
        self.field_widget_types[field_name] = "radiogroup"
        self._bind_hover_help(container, help_text)

    def _render_slider_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render a numeric threshold field as a slider with a live value label."""

        slider_config = self.SLIDER_FIELDS[field_name]
        default_value = float(SCALAR_FIELD_DEFAULTS.get(field_name, slider_config["from_"]))
        variable = tk.DoubleVar(value=default_value)
        container = ttk.Frame(frame)
        container.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        container.columnconfigure(0, weight=1)
        widget = ttk.Scale(
            container,
            from_=slider_config["from_"],
            to=slider_config["to"],
            variable=variable,
            command=lambda _value, name=field_name: self._sync_slider_label(name),
        )
        widget.grid(row=0, column=0, sticky="ew")
        value_label = ttk.Label(container, width=8, anchor="e")
        value_label.grid(row=0, column=1, padx=(8, 0))
        self.slider_value_labels[field_name] = value_label
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self.field_widget_types[field_name] = "slider"
        self._bind_hover_help(widget, help_text)
        self._sync_slider_label(field_name)

    def _render_combobox_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render a field as an editable dropdown with suggested presets."""

        variable = tk.StringVar(value=str(SCALAR_FIELD_DEFAULTS.get(field_name, "")))
        widget = ttk.Combobox(frame, textvariable=variable, values=self.COMBOBOX_FIELDS[field_name], state="normal")
        widget.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self.field_widget_types[field_name] = "combobox"
        self._bind_hover_help(widget, help_text)

    def _render_spinbox_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render bounded integer settings as spinboxes."""

        spinbox_config = self.SPINBOX_FIELDS[field_name]
        variable = tk.IntVar(value=int(SCALAR_FIELD_DEFAULTS.get(field_name, spinbox_config["from_"])))
        widget = ttk.Spinbox(
            frame,
            from_=spinbox_config["from_"],
            to=spinbox_config["to"],
            increment=spinbox_config["increment"],
            textvariable=variable,
        )
        widget.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self.field_widget_types[field_name] = "spinbox"
        self._bind_hover_help(widget, help_text)

    def _render_path_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render filesystem paths with an entry plus a browse button."""

        variable = tk.StringVar(value=str(SCALAR_FIELD_DEFAULTS.get(field_name, "")))
        container = ttk.Frame(frame)
        container.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        container.columnconfigure(0, weight=1)
        widget = ttk.Entry(container, textvariable=variable)
        widget.grid(row=0, column=0, sticky="ew")
        browse_button = ttk.Button(
            container,
            text="Browse",
            command=lambda name=field_name, var=variable: self._browse_for_field(name, var),
        )
        browse_button.grid(row=0, column=1, padx=(6, 0))
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self.field_widget_types[field_name] = "path"
        self._bind_hover_help(widget, help_text)
        self._bind_hover_help(browse_button, help_text)

    def _render_entry_field(self, frame: ttk.LabelFrame, field_name: str, help_text: str, row: int) -> None:
        """Render a plain text entry, masking secrets when appropriate."""

        variable = tk.StringVar(value=str(SCALAR_FIELD_DEFAULTS.get(field_name, "")))
        entry_kwargs: dict[str, Any] = {"textvariable": variable}
        if field_name in self.SECRET_FIELDS:
            entry_kwargs["show"] = "*"
        widget = ttk.Entry(frame, **entry_kwargs)
        widget.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.scalar_vars[field_name] = variable
        self.field_input_widgets[field_name] = widget
        self.field_focus_widgets[field_name] = widget
        self.field_widget_types[field_name] = "entry"
        self._bind_hover_help(widget, help_text)

    def _help_text_for_field(self, field_name: str) -> str:
        """Return the explanatory hover text for one settings field."""

        if field_name in self.FIELD_HELP_TEXTS:
            return self.FIELD_HELP_TEXTS[field_name]
        label = self.LABELS.get(field_name, field_name.replace("_", " ").replace("-", " ").title())
        if field_name.endswith(("_dir", "_path")):
            return f"Filesystem location used for {label.lower()}."
        if field_name.endswith("_api_key"):
            return f"Credential used for {label.lower()}. Leave it blank if the provider is not enabled."
        if field_name.startswith("output_"):
            return f"Toggle whether {label.lower()} artifacts are written after the run."
        if field_name.startswith("log_"):
            return f"Toggle whether {label.lower()} details are shown in verbose or debug logging."
        if field_name in BOOLEAN_FIELD_DEFAULTS or field_name.endswith("_enabled"):
            return f"Turn {label.lower()} on or off for this run."
        return f"Configure {label.lower()} for this run. This value is saved into profiles and JSON configs."

    def _build_settings_quick_access(self, parent: ttk.LabelFrame) -> None:
        """Create searchable shortcuts and live summaries for the most requested settings."""

        intro = ttk.Label(
            parent,
            text=(
                "Use the direct controls below for the most important settings, or use search and jump buttons to find "
                "model selection, chained passes, thresholds, CSV/SQLite outputs, PDF folders, and verbose logging immediately."
            ),
            wraplength=1040,
            justify="left",
        )
        intro.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        search_bar = ttk.Frame(parent)
        search_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        search_bar.columnconfigure(1, weight=1)
        search_bar.columnconfigure(2, weight=1)
        ttk.Label(search_bar, text="Find setting:").grid(row=0, column=0, sticky="w")
        search_entry = ttk.Entry(search_bar, textvariable=self.settings_search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        search_entry.bind("<KeyRelease>", lambda _event: self._refresh_settings_search_results())
        search_entry.bind("<Return>", lambda _event: self._focus_selected_setting())
        self.settings_search_combo = ttk.Combobox(search_bar, textvariable=self.settings_search_choice_var, state="readonly")
        self.settings_search_combo.grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.settings_search_combo.bind("<<ComboboxSelected>>", lambda _event: self._focus_selected_setting())
        ttk.Button(search_bar, text="Go", command=self._focus_selected_setting).grid(row=0, column=3)

        jump_bar = ttk.Frame(parent)
        jump_bar.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))
        jumps = [
            ("Jump to Models", lambda: self._focus_field("llm_provider")),
            ("Jump to Thresholds", lambda: self._focus_field("relevance_threshold")),
            ("Jump to Outputs", lambda: self._focus_field("output_csv")),
            ("Jump to Storage Paths", lambda: self._focus_field("database_path")),
            ("Jump to Logging", lambda: self._focus_field("verbosity")),
            ("Edit Pass Chain", self._open_pass_builder),
        ]
        for text, command in jumps:
            button = ttk.Button(jump_bar, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._bind_hover_help(button, f"Jump to the GUI area for {text.lower()}.")

        guide_bar = ttk.Frame(parent)
        guide_bar.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        guide_buttons = [
            ("Open Model Guide", lambda: self._open_handbook_entry("guide:models")),
            ("Open Output Guide", lambda: self._open_handbook_entry("guide:outputs")),
            ("Open API Guide", lambda: self._open_handbook_entry("guide:api_keys")),
            ("Open Actions Guide", lambda: self._open_handbook_entry("guide:actions")),
        ]
        for text, command in guide_buttons:
            button = ttk.Button(guide_bar, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._bind_hover_help(button, f"Open the handbook entry for {text.lower()}.")

        controls_frame = ttk.LabelFrame(parent, text="Most-Used Controls", padding=8)
        controls_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        controls_frame.columnconfigure(1, weight=1)
        controls_frame.columnconfigure(3, weight=1)
        self.quick_access_controls_frame = controls_frame

        model_frame = ttk.LabelFrame(parent, text="Current Model Setup", padding=8)
        model_frame.grid(row=5, column=0, sticky="nsew", padx=(0, 6))
        output_frame = ttk.LabelFrame(parent, text="Current Output Paths", padding=8)
        output_frame.grid(row=5, column=1, sticky="nsew", padx=(6, 0))
        parent.rowconfigure(5, weight=1)
        model_frame.rowconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        model_frame.columnconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)

        self.model_summary_text = scrolledtext.ScrolledText(model_frame, height=10, wrap="word", state="disabled")
        self.model_summary_text.grid(row=0, column=0, sticky="nsew")
        self.output_summary_text = scrolledtext.ScrolledText(output_frame, height=10, wrap="word", state="disabled")
        self.output_summary_text.grid(row=0, column=0, sticky="nsew")

    def _populate_quick_access_controls(self) -> None:
        """Mirror the most-used settings at the top of the Settings tab for immediate editing."""

        frame = getattr(self, "quick_access_controls_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()

        ttk.Label(
            frame,
            text=(
                "These controls mirror the full settings below. Use them to pick the model, adjust thresholds, decide "
                "whether PDFs should be downloaded, and set the main storage paths without hunting through the form."
            ),
            wraplength=1040,
            justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        def add_label(row: int, column: int, field_name: str) -> None:
            label = ttk.Label(frame, text=self.LABELS.get(field_name, field_name.replace("_", " ").title()))
            label.grid(row=row, column=column, sticky="w", padx=4, pady=4)
            self._bind_hover_help(label, self._help_text_for_field(field_name))

        def add_path_control(row: int, field_name: str) -> None:
            add_label(row, 0, field_name)
            variable = self.scalar_vars[field_name]
            container = ttk.Frame(frame)
            container.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
            container.columnconfigure(0, weight=1)
            entry = ttk.Entry(container, textvariable=variable)
            entry.grid(row=0, column=0, sticky="ew")
            browse_button = ttk.Button(
                container,
                text="Browse",
                command=lambda name=field_name, var=variable: self._browse_for_field(name, var),
            )
            browse_button.grid(row=0, column=1, padx=(6, 0))
            self._bind_hover_help(entry, self._help_text_for_field(field_name))
            self._bind_hover_help(browse_button, self._help_text_for_field(field_name))

        add_label(1, 0, "llm_provider")
        llm_provider_widget = ttk.Combobox(
            frame,
            textvariable=self.scalar_vars["llm_provider"],
            values=self.COMBOBOX_FIELDS["llm_provider"],
            state="normal",
        )
        llm_provider_widget.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self._bind_hover_help(llm_provider_widget, self._help_text_for_field("llm_provider"))

        edit_pass_button = ttk.Button(frame, text="Edit Pass Chain", command=self._open_pass_builder)
        edit_pass_button.grid(row=1, column=2, sticky="w", padx=4, pady=4)
        self._bind_hover_help(edit_pass_button, self._help_text_for_field("analysis_passes"))
        threshold_button = ttk.Button(frame, text="Jump to Thresholds", command=lambda: self._focus_field("relevance_threshold"))
        threshold_button.grid(row=1, column=3, sticky="w", padx=4, pady=4)
        self._bind_hover_help(threshold_button, self._help_text_for_field("relevance_threshold"))

        for row, field_name in enumerate(("openai_model", "gemini_model", "ollama_model", "huggingface_model"), start=2):
            add_label(row, 0, field_name)
            widget = ttk.Combobox(
                frame,
                textvariable=self.scalar_vars[field_name],
                values=self.COMBOBOX_FIELDS[field_name],
                state="normal",
            )
            widget.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
            self._bind_hover_help(widget, self._help_text_for_field(field_name))

        download_row = 2 + len(("openai_model", "gemini_model", "ollama_model", "huggingface_model"))

        download_widget = ttk.Checkbutton(
            frame,
            text=self.LABELS["download_pdfs"],
            variable=self.scalar_vars["download_pdfs"],
        )
        download_widget.grid(row=download_row, column=0, sticky="w", padx=4, pady=4)
        self._bind_hover_help(download_widget, self._help_text_for_field("download_pdfs"))
        add_label(download_row, 1, "pdf_download_mode")
        pdf_mode_frame = ttk.Frame(frame)
        pdf_mode_frame.grid(row=download_row, column=2, columnspan=2, sticky="w", padx=4, pady=4)
        for index, option in enumerate(self.RADIO_FIELDS["pdf_download_mode"]):
            button = ttk.Radiobutton(
                pdf_mode_frame,
                text=option,
                value=option,
                variable=self.scalar_vars["pdf_download_mode"],
            )
            button.grid(row=0, column=index, sticky="w", padx=(0, 8))
            self._bind_hover_help(button, self._help_text_for_field("pdf_download_mode"))

        csv_widget = ttk.Checkbutton(frame, text=self.LABELS["output_csv"], variable=self.scalar_vars["output_csv"])
        csv_widget.grid(row=download_row + 1, column=0, sticky="w", padx=4, pady=4)
        sqlite_widget = ttk.Checkbutton(
            frame,
            text=self.LABELS["output_sqlite_exports"],
            variable=self.scalar_vars["output_sqlite_exports"],
        )
        sqlite_widget.grid(row=download_row + 1, column=1, sticky="w", padx=4, pady=4)
        self._bind_hover_help(csv_widget, self._help_text_for_field("output_csv"))
        self._bind_hover_help(sqlite_widget, self._help_text_for_field("output_sqlite_exports"))

        add_path_control(download_row + 2, "database_path")
        add_path_control(download_row + 3, "results_dir")
        add_path_control(download_row + 4, "papers_dir")
        add_path_control(download_row + 5, "relevant_pdfs_dir")

        for column in range(4):
            frame.columnconfigure(column, weight=1 if column in {1, 3} else 0)

    def _settings_index(self) -> list[tuple[str, str]]:
        """Return searchable setting targets in a human-readable label format."""

        entries: list[tuple[str, str]] = []
        for section_name, field_names in self.GROUPS:
            for field_name in field_names:
                label = self.LABELS.get(field_name, field_name.replace("_", " ").title())
                entries.append((field_name, f"{section_name} -> {label}"))
        return entries

    def _refresh_settings_search_results(self) -> None:
        """Filter the settings search list based on the current query string."""

        if self.settings_search_combo is None:
            return
        query = self.settings_search_var.get().strip().lower()
        matches: list[str] = []
        for field_name, display in self._settings_index():
            haystack = " ".join([display, self._help_text_for_field(field_name)]).lower()
            if query and query not in haystack:
                continue
            matches.append(display)
        self.settings_search_combo["values"] = matches
        if matches:
            self.settings_search_choice_var.set(matches[0])
        else:
            self.settings_search_choice_var.set("")

    def _focus_selected_setting(self) -> None:
        """Scroll to the setting chosen in the quick-access search box."""

        selected = self.settings_search_choice_var.get().strip()
        if not selected:
            return
        for field_name, display in self._settings_index():
            if display == selected:
                self._focus_field(field_name)
                break

    def _focus_field(self, field_name: str) -> None:
        """Scroll the settings canvas to a field and focus its primary widget."""

        widget = self.field_focus_widgets.get(field_name)
        if widget is None:
            return
        self.notebook.select(self.settings_tab)
        page_name = self.field_to_settings_page.get(field_name)
        if page_name and self.settings_pages_notebook is not None and page_name in self.settings_page_frames:
            self.settings_pages_notebook.select(self.settings_page_frames[page_name])
        try:
            widget.focus_set()
        except tk.TclError:
            pass
        self._show_hover_help(self._help_text_for_field(field_name))
        self._set_status(f"Focused setting: {self.LABELS.get(field_name, field_name)}")

    def _scroll_widget_into_view(self, widget: tk.Widget) -> None:
        """Preserve the old focus helper contract for tests and future layout changes.

        The settings UI now uses notebook pages rather than a scrollable canvas, so focusing the
        correct page is enough for visibility in the current layout. This helper intentionally
        stays lightweight instead of reintroducing the removed canvas-specific scroll code.
        """

        try:
            widget.update_idletasks()
        except tk.TclError:
            return

    def _format_slider_value(self, field_name: str, value: float) -> str:
        """Format slider-backed numeric values consistently for display labels."""

        slider_config = self.SLIDER_FIELDS[field_name]
        rounded = round(value / slider_config["resolution"]) * slider_config["resolution"]
        digits = slider_config["digits"]
        if digits == 0:
            return str(int(round(rounded)))
        return f"{rounded:.{digits}f}"

    def _sync_slider_label(self, field_name: str) -> None:
        """Keep the slider value label in sync with the underlying Tk variable."""

        variable = self.scalar_vars.get(field_name)
        label = self.slider_value_labels.get(field_name)
        if variable is None or label is None:
            return
        try:
            value = float(variable.get())
        except (TypeError, ValueError):
            return
        formatted = self._format_slider_value(field_name, value)
        label.configure(text=formatted)
        self._refresh_settings_overview()

    def _register_settings_observers(self) -> None:
        """Attach lightweight observers so overview panels stay in sync with form edits."""

        for field_name, variable in self.scalar_vars.items():
            variable.trace_add("write", lambda *_args, name=field_name: self._handle_setting_change(name))
        analysis_widget = self.text_widgets.get("analysis_passes")
        if analysis_widget is not None:
            analysis_widget.bind("<KeyRelease>", lambda _event: self._refresh_settings_overview(), add="+")

    def _handle_setting_change(self, field_name: str) -> None:
        """Update derived UI state after one scalar setting changes."""

        if field_name in self.slider_value_labels:
            self._sync_slider_label(field_name)
            return
        self._refresh_settings_overview()

    def _refresh_settings_overview(self) -> None:
        """Update the quick-access summaries for model configuration and outputs."""

        values = self._collect_form_values()
        results_dir = Path(str(values.get("results_dir", "results") or "results"))
        papers_dir = Path(str(values.get("papers_dir", "papers") or "papers"))
        relevant_dir_raw = str(values.get("relevant_pdfs_dir", "") or "").strip()
        relevant_dir = Path(relevant_dir_raw) if relevant_dir_raw else papers_dir / "relevant"
        pdf_mode = str(values.get("pdf_download_mode", "all") or "all")
        chain_entries = self._current_analysis_passes()
        model_lines = [
            f"Primary provider: {values.get('llm_provider', 'auto')}",
            f"Chained pass setup: {'yes' if chain_entries else 'no'}",
            f"OpenAI model: {values.get('openai_model', '') or '(not set)'}",
            f"Gemini model: {values.get('gemini_model', '') or '(not set)'}",
            f"Ollama model: {values.get('ollama_model', '') or '(not set)'}",
            f"HF model: {values.get('huggingface_model', '') or '(not set)'}",
            f"Relevance threshold: {values.get('relevance_threshold')}",
            f"Maybe margin: {values.get('maybe_threshold_margin')}",
            f"LLM temperature: {values.get('llm_temperature')}",
        ]
        if chain_entries:
            model_lines.append("")
            model_lines.append("Pass chain:")
            for index, entry in enumerate(chain_entries, start=1):
                line = (
                    f"{index}. {entry['name']} -> {entry['provider']} | threshold {int(round(float(entry['threshold'])))} "
                    f"| {entry['decision_mode']} | maybe {int(round(float(entry['margin'])))}"
                )
                if entry.get("model_name"):
                    line += f" | model {entry['model_name']}"
                if entry.get("min_input_score") not in {None, ''}:
                    line += f" | start if previous >= {int(round(float(entry['min_input_score'])))}"
                model_lines.append(line)
        output_lines = [
            f"Main SQLite DB: {values.get('database_path')}",
            f"CSV exports: {'on' if values.get('output_csv') else 'off'} -> {results_dir / 'papers.csv'}",
            f"JSON exports: {'on' if values.get('output_json') else 'off'} -> {results_dir / 'top_papers.json'}",
            f"Markdown summary: {'on' if values.get('output_markdown') else 'off'} -> {results_dir / 'review_summary.md'}",
            f"SQLite exports: {'on' if values.get('output_sqlite_exports') else 'off'} -> {results_dir / 'included_papers.db'}",
            f"PDF downloads: {'on' if values.get('download_pdfs') else 'off'} | mode={pdf_mode}",
            f"Main PDF folder: {papers_dir}",
        ]
        if pdf_mode == "relevant_only":
            folder_mode = "same folder" if relevant_dir == papers_dir else "separate relevant folder"
            output_lines.append(f"Relevant PDF folder: {relevant_dir} ({folder_mode})")
        else:
            output_lines.append("Relevant PDFs are not split into a separate folder in 'all' mode.")
        output_lines.append(f"Results folder: {results_dir}")

        self._write_summary_widget(self.model_summary_text, "\n".join(model_lines))
        self._write_summary_widget(self.output_summary_text, "\n".join(output_lines))

    def _write_summary_widget(self, widget: scrolledtext.ScrolledText | None, text: str) -> None:
        """Render summary text into a read-only scrolled text widget."""

        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _bind_hover_help(self, widget: tk.Widget, help_text: str) -> None:
        """Attach hover and keyboard-focus help handlers to a settings widget."""

        widget.bind("<Enter>", lambda event, text=help_text: self._show_hover_help(text, event), add="+")
        widget.bind("<Leave>", lambda _event: self._clear_hover_help(), add="+")
        widget.bind("<FocusIn>", lambda event, text=help_text: self._show_hover_help(text, event), add="+")
        widget.bind("<FocusOut>", lambda _event: self._clear_hover_help(), add="+")

    def _toggle_hover_help(self) -> None:
        """Enable or disable contextual hover help without changing other UI state."""

        if not self.hover_help_enabled.get():
            self._clear_hover_help()
            return
        self._set_status("Hover help enabled. Move over a setting to see what it does.")

    def _show_hover_help(self, help_text: str, event: Any | None = None) -> None:
        """Show the current field explanation in both the status bar and a floating tooltip."""

        if not self.hover_help_enabled.get() or not help_text:
            return
        self._hover_message_active = True
        self.status_var.set(help_text)
        x_root = getattr(event, "x_root", self.root.winfo_pointerx())
        y_root = getattr(event, "y_root", self.root.winfo_pointery())
        self.hover_tooltip.show(help_text, x=x_root, y=y_root)

    def _clear_hover_help(self) -> None:
        """Restore the status bar after leaving a settings control."""

        self._hover_message_active = False
        self.hover_tooltip.hide()
        self.status_var.set(self.base_status_message)

    def _set_status(self, message: str) -> None:
        """Store the current persistent status message and show it when hover help is idle."""

        self.base_status_message = message
        if not self._hover_message_active:
            self.status_var.set(message)

    def _build_handbook_entries(self) -> dict[str, dict[str, str]]:
        """Assemble searchable handbook content from guides, sections, and field help text."""

        entries: dict[str, dict[str, str]] = {}
        for key, (group, title, body) in self.HANDBOOK_GUIDES.items():
            entries[key] = {"group": group, "title": title, "body": body}
        for section_name, _field_names in self.GROUPS:
            entries[f"section:{section_name}"] = {
                "group": "Section",
                "title": section_name,
                "body": self.SECTION_HELP_TEXTS.get(section_name, section_name),
            }
        for section_name, field_names in self.GROUPS:
            for field_name in field_names:
                label = self.LABELS.get(field_name, field_name.replace("_", " ").title())
                entries[f"field:{field_name}"] = {
                    "group": section_name,
                    "title": label,
                    "body": self._help_text_for_field(field_name),
                }
        return entries

    def _build_handbook_tab(self) -> None:
        """Create a searchable in-app handbook for all UI and CLI-exposed settings."""

        container = ttk.Frame(self.handbook_tab, padding=8)
        container.pack(fill="both", expand=True)

        filter_bar = ttk.Frame(container)
        filter_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(filter_bar, text="Search handbook:").pack(side="left")
        search_entry = ttk.Entry(filter_bar, textvariable=self.handbook_search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        search_entry.bind("<KeyRelease>", lambda _event: self._refresh_handbook_tree())

        body = ttk.Frame(container)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.handbook_tree = ttk.Treeview(left, columns=("group", "setting"), show="headings", height=24)
        self.handbook_tree.heading("group", text="Group")
        self.handbook_tree.heading("setting", text="Setting / Guide")
        self.handbook_tree.column("group", width=170, anchor="w")
        self.handbook_tree.column("setting", width=260, anchor="w")
        self.handbook_tree.pack(fill="y", expand=False)
        self.handbook_tree.bind("<<TreeviewSelect>>", self._handle_handbook_selection)

        self.handbook_text = scrolledtext.ScrolledText(right, wrap="word", state="disabled")
        self.handbook_text.pack(fill="both", expand=True)

        self._refresh_handbook_tree()

    def _refresh_handbook_tree(self) -> None:
        """Apply the handbook search filter and repopulate the handbook index."""

        if self.handbook_tree is None:
            return
        search_text = self.handbook_search_var.get().strip().lower()
        for item in self.handbook_tree.get_children():
            self.handbook_tree.delete(item)

        visible_keys: list[str] = []
        for key, entry in self.handbook_entries.items():
            haystack = " ".join([entry["group"], entry["title"], entry["body"]]).lower()
            if search_text and search_text not in haystack:
                continue
            self.handbook_tree.insert("", tk.END, iid=key, values=[entry["group"], entry["title"]])
            visible_keys.append(key)

        if visible_keys:
            first_key = visible_keys[0]
            self.handbook_tree.selection_set(first_key)
            self.handbook_tree.focus(first_key)
            self._render_handbook_entry(first_key)
        else:
            self._render_handbook_text("No handbook entries match the current search.")

    def _handle_handbook_selection(self, _event: Any) -> None:
        """Render the currently selected handbook entry."""

        if self.handbook_tree is None:
            return
        selection = self.handbook_tree.selection()
        if not selection:
            return
        self._render_handbook_entry(selection[0])

    def _render_handbook_entry(self, key: str) -> None:
        """Render one handbook entry into the handbook detail pane."""

        entry = self.handbook_entries.get(key)
        if not entry:
            self._render_handbook_text("No handbook content is available for this selection.")
            return
        self._render_handbook_text(f"{entry['title']}\n\nGroup: {entry['group']}\n\n{entry['body']}")

    def _open_handbook_entry(self, key: str) -> None:
        """Switch to the handbook tab and focus a specific guide entry when available."""

        if self.notebook is not None:
            self.notebook.select(self.handbook_tab)
        if self.handbook_tree is None:
            return
        if key in self.handbook_entries:
            self.handbook_search_var.set("")
            self._refresh_handbook_tree()
            self.handbook_tree.selection_set(key)
            self.handbook_tree.focus(key)
            self._render_handbook_entry(key)

    def _render_handbook_text(self, text: str) -> None:
        """Write handbook text into the read-only handbook detail widget."""

        if self.handbook_text is None:
            return
        self.handbook_text.configure(state="normal")
        self.handbook_text.delete("1.0", tk.END)
        self.handbook_text.insert("1.0", text)
        self.handbook_text.configure(state="disabled")

    def _browse_for_field(self, field_name: str, variable: tk.StringVar) -> None:
        """Open a file or directory chooser for settings that point at local paths."""

        mode = self.PATH_FIELD_MODES.get(field_name)
        selected = ""
        if mode == "directory":
            selected = filedialog.askdirectory()
        elif mode == "save_file":
            selected = filedialog.asksaveasfilename(
                defaultextension=".db",
                filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
            )
        elif mode == "file":
            selected = filedialog.askopenfilename(
                filetypes=[
                    ("Supported files", "*.json *.csv *.db *.txt *.ris *.bib"),
                    ("JSON files", "*.json"),
                    ("CSV files", "*.csv"),
                    ("All files", "*.*"),
                ]
            )
        if selected:
            variable.set(selected)
            self._set_status(f"Updated {self.LABELS.get(field_name, field_name)} to {selected}")

    def _current_analysis_passes(self) -> list[dict[str, Any]]:
        """Parse the analysis-pass text area into structured pass definitions."""

        widget = self.text_widgets.get("analysis_passes")
        if widget is None:
            return []
        lines = [line.strip() for line in widget.get("1.0", tk.END).splitlines() if line.strip()]
        passes: list[dict[str, Any]] = []
        for line in lines:
            parsed = parse_analysis_pass(line)
            passes.append(
                {
                    "name": parsed.name,
                    "provider": parsed.llm_provider,
                    "threshold": parsed.threshold,
                    "decision_mode": parsed.decision_mode,
                    "margin": parsed.maybe_threshold_margin,
                    "model_name": parsed.model_name or "",
                    "min_input_score": parsed.min_input_score,
                }
            )
        return passes

    def _write_analysis_passes(self, passes: list[dict[str, Any]]) -> None:
        """Rewrite the analysis-pass text area from structured pass definitions."""

        widget = self.text_widgets.get("analysis_passes")
        if widget is None:
            return
        lines = [
            "|".join(
                [
                    str(entry["name"]),
                    str(entry["provider"]),
                    f"{float(entry['threshold']):.0f}",
                    str(entry["decision_mode"]),
                    f"{float(entry['margin']):.0f}",
                    str(entry.get("model_name", "") or ""),
                    (
                        ""
                        if entry.get("min_input_score") in {None, ""}
                        else f"{float(entry['min_input_score']):.0f}"
                    ),
                ]
            )
            for entry in passes
        ]
        self._set_text_widget_value(widget, "\n".join(lines))
        self._refresh_settings_overview()

    def _open_pass_builder(self) -> None:
        """Open a small visual editor for chained multi-pass model configuration."""

        entries = self._current_analysis_passes()
        if not entries:
            entries = [
                {
                    "name": "fast",
                    "provider": "huggingface_local",
                    "threshold": 70.0,
                    "decision_mode": "strict",
                    "margin": 10.0,
                }
            ]

        dialog = tk.Toplevel(self.root)
        dialog.title("Analysis Pass Builder")
        dialog.geometry("900x520")
        dialog.transient(self.root)

        left = ttk.Frame(dialog, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(dialog, padding=10)
        right.pack(side="left", fill="both", expand=True)

        tree = ttk.Treeview(
            left,
            columns=("name", "provider", "threshold", "mode", "margin", "model", "min_score"),
            show="headings",
            height=16,
        )
        for column, title, width in (
            ("name", "Pass", 120),
            ("provider", "Provider", 180),
            ("threshold", "Threshold", 90),
            ("mode", "Mode", 100),
            ("margin", "Maybe", 90),
            ("model", "Model override", 220),
            ("min_score", "Start if prev >=", 120),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w")
        tree.pack(fill="y", expand=False)

        form_vars = {
            "name": tk.StringVar(value="fast"),
            "provider": tk.StringVar(value="huggingface_local"),
            "decision_mode": tk.StringVar(value="strict"),
            "threshold": tk.DoubleVar(value=70.0),
            "margin": tk.DoubleVar(value=10.0),
            "model_name": tk.StringVar(value=""),
            "min_input_score_enabled": tk.BooleanVar(value=False),
            "min_input_score": tk.DoubleVar(value=70.0),
        }
        threshold_label = ttk.Label(right, width=8, anchor="e")
        margin_label = ttk.Label(right, width=8, anchor="e")
        min_input_score_label = ttk.Label(right, width=8, anchor="e")

        def refresh_tree() -> None:
            for item in tree.get_children():
                tree.delete(item)
            for index, entry in enumerate(entries):
                tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=[
                        entry["name"],
                        entry["provider"],
                        int(round(float(entry["threshold"]))),
                        entry["decision_mode"],
                        int(round(float(entry["margin"]))),
                        entry.get("model_name", "") or "",
                        (
                            int(round(float(entry["min_input_score"])))
                            if entry.get("min_input_score") not in {None, ""}
                            else "always"
                        ),
                    ],
                )
            if entries:
                selected = tree.selection() or (tree.get_children()[0],)
                tree.selection_set(selected[0])
                tree.focus(selected[0])
                load_selected()

        def sync_labels() -> None:
            threshold_label.configure(text=str(int(round(form_vars["threshold"].get()))))
            margin_label.configure(text=str(int(round(form_vars["margin"].get()))))
            if form_vars["min_input_score_enabled"].get():
                min_input_score_label.configure(text=str(int(round(form_vars["min_input_score"].get()))))
            else:
                min_input_score_label.configure(text="always")

        def load_selected(_event: Any | None = None) -> None:
            selection = tree.selection()
            if not selection:
                return
            entry = entries[int(selection[0])]
            form_vars["name"].set(entry["name"])
            form_vars["provider"].set(entry["provider"])
            form_vars["decision_mode"].set(entry["decision_mode"])
            form_vars["threshold"].set(float(entry["threshold"]))
            form_vars["margin"].set(float(entry["margin"]))
            form_vars["model_name"].set(str(entry.get("model_name", "") or ""))
            min_input_score = entry.get("min_input_score")
            if min_input_score in {None, ""}:
                form_vars["min_input_score_enabled"].set(False)
                form_vars["min_input_score"].set(float(entry.get("threshold", 70.0)))
            else:
                form_vars["min_input_score_enabled"].set(True)
                form_vars["min_input_score"].set(float(min_input_score))
            sync_labels()

        def save_current() -> None:
            name = form_vars["name"].get().strip()
            if not name:
                messagebox.showerror("Pass name required", "Enter a pass name before saving.", parent=dialog)
                return
            entry = {
                "name": name,
                "provider": form_vars["provider"].get().strip(),
                "threshold": float(form_vars["threshold"].get()),
                "decision_mode": form_vars["decision_mode"].get().strip(),
                "margin": float(form_vars["margin"].get()),
                "model_name": form_vars["model_name"].get().strip(),
                "min_input_score": (
                    float(form_vars["min_input_score"].get())
                    if form_vars["min_input_score_enabled"].get()
                    else None
                ),
            }
            selection = tree.selection()
            if selection:
                entries[int(selection[0])] = entry
            else:
                entries.append(entry)
            refresh_tree()

        def add_pass() -> None:
            entries.append(
                {
                    "name": f"pass_{len(entries) + 1}",
                    "provider": form_vars["provider"].get().strip(),
                    "threshold": float(form_vars["threshold"].get()),
                    "decision_mode": form_vars["decision_mode"].get().strip(),
                    "margin": float(form_vars["margin"].get()),
                    "model_name": form_vars["model_name"].get().strip(),
                    "min_input_score": (
                        float(form_vars["min_input_score"].get())
                        if form_vars["min_input_score_enabled"].get()
                        else None
                    ),
                }
            )
            refresh_tree()
            tree.selection_set(str(len(entries) - 1))
            load_selected()

        def remove_pass() -> None:
            selection = tree.selection()
            if not selection:
                return
            entries.pop(int(selection[0]))
            refresh_tree()

        def move(offset: int) -> None:
            selection = tree.selection()
            if not selection:
                return
            current_index = int(selection[0])
            target_index = current_index + offset
            if target_index < 0 or target_index >= len(entries):
                return
            entries[current_index], entries[target_index] = entries[target_index], entries[current_index]
            refresh_tree()
            tree.selection_set(str(target_index))
            load_selected()

        tree.bind("<<TreeviewSelect>>", load_selected)

        ttk.Label(right, text="Pass name").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(right, textvariable=form_vars["name"]).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Provider").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            right,
            textvariable=form_vars["provider"],
            values=["heuristic", "openai_compatible", "gemini", "ollama", "huggingface_local"],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Decision mode").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            right,
            textvariable=form_vars["decision_mode"],
            values=["strict", "triage"],
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Threshold (%)").grid(row=3, column=0, sticky="w", pady=4)
        threshold_scale = ttk.Scale(right, from_=0, to=100, variable=form_vars["threshold"], command=lambda _value: sync_labels())
        threshold_scale.grid(row=3, column=1, sticky="ew", pady=4)
        threshold_label.grid(row=3, column=2, sticky="e", padx=(8, 0))
        ttk.Label(right, text="Maybe margin (%)").grid(row=4, column=0, sticky="w", pady=4)
        margin_scale = ttk.Scale(right, from_=0, to=100, variable=form_vars["margin"], command=lambda _value: sync_labels())
        margin_scale.grid(row=4, column=1, sticky="ew", pady=4)
        margin_label.grid(row=4, column=2, sticky="e", padx=(8, 0))
        ttk.Label(right, text="Model override").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(right, textvariable=form_vars["model_name"]).grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)
        min_gate_frame = ttk.Frame(right)
        min_gate_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Checkbutton(
            min_gate_frame,
            text="Only run this pass if the previous pass scored at least",
            variable=form_vars["min_input_score_enabled"],
            command=sync_labels,
        ).pack(side="left")
        min_gate_scale = ttk.Scale(
            right,
            from_=0,
            to=100,
            variable=form_vars["min_input_score"],
            command=lambda _value: sync_labels(),
        )
        min_gate_scale.grid(row=7, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Entry score gate (%)").grid(row=7, column=0, sticky="w", pady=4)
        min_input_score_label.grid(row=7, column=2, sticky="e", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        sync_labels()

        button_bar = ttk.Frame(right)
        button_bar.grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Button(button_bar, text="Add Pass", command=add_pass).pack(side="left")
        ttk.Button(button_bar, text="Update Pass", command=save_current).pack(side="left", padx=(6, 0))
        ttk.Button(button_bar, text="Remove Pass", command=remove_pass).pack(side="left", padx=(6, 0))
        ttk.Button(button_bar, text="Move Up", command=lambda: move(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(button_bar, text="Move Down", command=lambda: move(1)).pack(side="left", padx=(6, 0))

        footer = ttk.Frame(right)
        footer.grid(row=9, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(footer, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(
            footer,
            text="Apply",
            command=lambda: (self._write_analysis_passes(entries), self._set_status("Updated analysis pass chain."), dialog.destroy()),
        ).pack(side="right", padx=(0, 8))

        refresh_tree()

    def _build_log_tab(self) -> None:
        """Create the read-only live log panel."""

        self.log_widget = scrolledtext.ScrolledText(self.log_tab, wrap="word", state="disabled")
        self.log_widget.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_table_tab(self, parent: ttk.Frame, key: str, *, include_filters: bool = False) -> None:
        """Create a generic results table tab, optionally with filters for the full paper list."""

        container = ttk.Frame(parent, padding=8)
        container.pack(fill="both", expand=True)
        if include_filters:
            filter_bar = ttk.Frame(container)
            filter_bar.pack(fill="x", pady=(0, 8))
            ttk.Label(filter_bar, text="Filter:").pack(side="left")
            filter_combo = ttk.Combobox(
                filter_bar,
                textvariable=self.all_filter_var,
                state="readonly",
                values=["all", "screened_only"],
                width=16,
            )
            filter_combo.pack(side="left", padx=4)
            filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_all_table())
            ttk.Label(filter_bar, text="Search:").pack(side="left", padx=(12, 4))
            search_entry = ttk.Entry(filter_bar, textvariable=self.all_search_var)
            search_entry.pack(side="left", fill="x", expand=True)
            search_entry.bind("<KeyRelease>", lambda _event: self._refresh_all_table())

        tree = ttk.Treeview(container, show="headings")
        tree.pack(fill="both", expand=True)
        self.treeviews[key] = tree
        self.table_frames[key] = container

    def _build_outputs_tab(self) -> None:
        """Create the artifact list with open-on-click convenience actions."""

        container = ttk.Frame(self.outputs_tab, padding=8)
        container.pack(fill="both", expand=True)
        self.outputs_tree = ttk.Treeview(container, columns=("label", "path"), show="headings")
        self.outputs_tree.heading("label", text="Artifact")
        self.outputs_tree.heading("path", text="Path")
        self.outputs_tree.column("label", width=180, anchor="w")
        self.outputs_tree.column("path", width=950, anchor="w")
        self.outputs_tree.pack(fill="both", expand=True)
        button_bar = ttk.Frame(container)
        button_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(button_bar, text="Open Selected", command=self._open_selected_output).pack(side="left")

    def _apply_form_values(self, values: dict[str, Any]) -> None:
        """Populate the visible form controls from a flat dictionary of values."""

        for field_name, widget in self.text_widgets.items():
            self._set_text_widget_value(widget, str(values.get(field_name, "")))
        for field_name, variable in self.scalar_vars.items():
            variable.set(values.get(field_name, variable.get()))
        for field_name in self.slider_value_labels:
            self._sync_slider_label(field_name)
        self._refresh_settings_overview()

    def _collect_form_values(self) -> dict[str, Any]:
        """Read the current form state back out of Tk widgets into plain Python values."""

        values = default_form_values()
        for field_name, widget in self.text_widgets.items():
            values[field_name] = widget.get("1.0", tk.END).strip()
        for field_name, variable in self.scalar_vars.items():
            values[field_name] = variable.get()
        profile_name = self.profile_combo.get().strip()
        if profile_name and not values.get("profile_name"):
            values["profile_name"] = profile_name
        return values

    def _set_text_widget_value(self, widget: tk.Text, text: str) -> None:
        """Write text into a Tk text widget, temporarily unlocking read-only widgets when needed."""

        previous_state = str(widget.cget("state"))
        if previous_state == "disabled":
            widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        if previous_state == "disabled":
            widget.configure(state="disabled")

    def _load_config_file(self) -> None:
        """Open a JSON config file and hydrate the form with its validated values."""

        path = filedialog.askopenfilename(filetypes=[("JSON config", "*.json"), ("All files", "*.*")])
        if not path:
            return
        payload = load_config_file(path)
        values = config_payload_to_form_values(payload)
        self._apply_form_values(values)
        self._set_status(f"Loaded config from {path}")

    def _save_profile(self) -> None:
        """Persist the current form state as a reusable guided-UI profile."""

        values = self._collect_form_values()
        name = str(values.get("profile_name", "") or "").strip() or self.profile_combo.get().strip()
        if not name:
            messagebox.showerror("Profile name required", "Enter a profile name before saving.")
            return
        path = self.profile_manager.save_profile(name, values)
        self._refresh_profile_choices()
        self.profile_combo.set(name)
        self._set_status(f"Saved profile to {path}")

    def _load_profile(self) -> None:
        """Load the selected profile into the form."""

        name = self.profile_combo.get().strip() or str(self.scalar_vars.get("profile_name", tk.StringVar()).get()).strip()
        if not name:
            return
        values = self.profile_manager.load_profile(name)
        self._apply_form_values(values)
        self.profile_combo.set(name)
        self._set_status(f"Loaded profile '{name}'")

    def _refresh_profile_choices(self) -> None:
        """Refresh the profile dropdown after files are created or removed."""

        if hasattr(self, "profile_combo"):
            self.profile_combo["values"] = self.profile_manager.list_profiles()

    def _start_run(
        self,
        *,
        skip_discovery_override: bool | None = None,
        run_mode_override: str | None = None,
    ) -> None:
        """Validate the current form and launch the pipeline on a background worker thread."""

        if self.run_thread and self.run_thread.is_alive():
            messagebox.showinfo("Run in progress", "Wait for the current run to finish before starting another one.")
            return
        values = self._collect_form_values()
        if skip_discovery_override is not None:
            values["skip_discovery"] = skip_discovery_override
        if run_mode_override is not None:
            values["run_mode"] = run_mode_override
        try:
            config = form_values_to_config(values)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid configuration", str(exc))
            return
        logging.getLogger().setLevel(
            {
                "quiet": logging.WARNING,
                "normal": logging.INFO,
                "verbose": logging.INFO,
                "debug": logging.DEBUG,
            }.get(config.verbosity, logging.INFO)
        )

        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.configure(state="disabled")
        run_description = "Running pipeline..."
        if config.skip_discovery and config.run_mode == "analyze":
            run_description = "Running analysis from stored records..."
        elif config.skip_discovery:
            run_description = "Loading stored records without new discovery..."
        self._set_status(run_description)

        def worker() -> None:
            """Run the pipeline off the Tk main thread and return results through the queue."""

            controller: PipelineController | None = None
            try:
                controller = PipelineController(config, event_sink=self._emit_worker_event)
                self.current_controller = controller
                result = controller.run()
                self.message_queue.put(("result", {"config": config, "result": result}))
            except Exception as exc:  # noqa: BLE001
                self.message_queue.put(("error", str(exc)))
            finally:
                if self.current_controller is controller:
                    self.current_controller = None

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _force_stop(self) -> None:
        """Request a controlled stop of the currently running pipeline worker."""

        controller = self.current_controller
        if controller is None or self.run_thread is None or not self.run_thread.is_alive():
            self._set_status("No active run to stop.")
            return
        controller.request_stop()
        self._append_log("INFO | Stop requested by user. The pipeline will stop after the current operation.")
        self._set_status("Stop requested. Waiting for the current operation to finish safely.")

    def _emit_worker_event(self, event: dict[str, Any]) -> None:
        """Forward structured pipeline events from the worker thread into the UI queue."""

        self.message_queue.put(("event", event))

    def _poll_messages(self) -> None:
        """Drain queued log lines, status events, and results without blocking the UI."""

        try:
            while True:
                message_type, payload = self.message_queue.get_nowait()
                if message_type == "log":
                    self._append_log(payload)
                elif message_type == "event":
                    self._handle_event(payload)
                elif message_type == "result":
                    self._handle_result(payload)
                elif message_type == "error":
                    self._set_status(f"Run failed: {payload}")
                    self._append_log(f"ERROR | {payload}")
                    messagebox.showerror("Run failed", str(payload))
        except queue.Empty:
            pass
        # Tkinter stays responsive because the worker communicates only through this queued pump.
        self.root.after(100, self._poll_messages)

    def _append_log(self, message: str) -> None:
        """Append one line to the log tab and keep the newest output visible."""

        self.log_widget.configure(state="normal")
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state="disabled")

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Surface pipeline status events in the status bar."""

        event_type = event.get("event_type", "event")
        self._set_status(f"{event_type}: {event}")

    def _handle_result(self, payload: dict[str, Any]) -> None:
        """Refresh all result tabs after a successful pipeline run."""

        config = payload["config"]
        result = payload["result"]
        self.current_result = result
        status = result.get("run_status", "completed")
        self._set_status(f"Run finished with status: {status}")
        run_error = str(result.get("run_error", "") or "").strip()
        if status == "stopped" and run_error:
            messagebox.showwarning("Run stopped", run_error)
        elif status != "completed" and run_error:
            messagebox.showerror(f"Run status: {status}", run_error)
        self._load_dataframe_into_tree("all_papers", Path(str(result.get("papers_csv", config.results_dir / "papers.csv"))))
        self._load_dataframe_into_tree("included_papers", Path(str(result.get("included_papers_csv", config.results_dir / "included_papers.csv"))))
        self._load_dataframe_into_tree("excluded_papers", Path(str(result.get("excluded_papers_csv", config.results_dir / "excluded_papers.csv"))))
        self._load_outputs(result)

    def _refresh_results_from_disk(self) -> None:
        """Reload CSV artifacts from disk without rerunning the pipeline."""

        values = self._collect_form_values()
        config = form_values_to_config(values)
        self._load_dataframe_into_tree("all_papers", config.results_dir / "papers.csv")
        self._load_dataframe_into_tree("included_papers", config.results_dir / "included_papers.csv")
        self._load_dataframe_into_tree("excluded_papers", config.results_dir / "excluded_papers.csv")
        if not self.current_result:
            self.current_result = {"results_dir": str(config.results_dir)}
        self._load_outputs(self.current_result)
        self._set_status(f"Reloaded results from {config.results_dir}")

    def _load_dataframe_into_tree(self, key: str, path: Path) -> None:
        """Load a CSV file into one of the result tables."""

        tree = self.treeviews[key]
        for item in tree.get_children():
            tree.delete(item)
        if not path.exists():
            tree["columns"] = ()
            return
        dataframe = pd.read_csv(path)
        if key == "all_papers":
            dataframe = self._filter_all_papers(dataframe)
        columns = list(dataframe.columns[:12])
        tree["columns"] = columns
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=140, anchor="w")
        for _, row in dataframe[columns].fillna("").iterrows():
            tree.insert("", tk.END, values=[str(value)[:500] for value in row.tolist()])

    def _filter_all_papers(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Apply the current UI filter and free-text search to the full paper table."""

        filtered = dataframe
        if self.all_filter_var.get() == "screened_only" and "inclusion_decision" in filtered.columns:
            filtered = filtered[filtered["inclusion_decision"].fillna("").astype(str) != ""]
        search_text = self.all_search_var.get().strip().lower()
        if search_text:
            search_columns = [column for column in ("title", "authors", "abstract", "doi", "venue") if column in filtered.columns]
            if search_columns:
                mask = filtered[search_columns].fillna("").astype(str).apply(
                    lambda series: series.str.lower().str.contains(search_text, regex=False)
                )
                filtered = filtered[mask.any(axis=1)]
        return filtered

    def _refresh_all_table(self) -> None:
        """Reapply filters to the main paper table using the current results directory."""

        values = self._collect_form_values()
        config = form_values_to_config(values)
        self._load_dataframe_into_tree("all_papers", config.results_dir / "papers.csv")

    def _load_outputs(self, result: dict[str, Any]) -> None:
        """Populate the outputs tab from the latest result payload."""

        if self.outputs_tree is None:
            return
        for item in self.outputs_tree.get_children():
            self.outputs_tree.delete(item)
        for label, path in sorted(result.items()):
            if not isinstance(path, str):
                continue
            self.outputs_tree.insert("", tk.END, values=[label, path])

    def _open_results_dir(self) -> None:
        """Open the configured results directory in the platform file manager."""

        values = self._collect_form_values()
        config = form_values_to_config(values)
        self._open_path(Path(config.results_dir))

    def _open_selected_output(self) -> None:
        """Open the artifact currently selected in the outputs table."""

        if self.outputs_tree is None:
            return
        selection = self.outputs_tree.selection()
        if not selection:
            return
        item = self.outputs_tree.item(selection[0])
        values = item.get("values", [])
        if len(values) < 2:
            return
        self._open_path(Path(values[1]))

    def _open_path(self, path: Path) -> None:
        """Open a file or directory using the host operating system defaults."""

        if not path.exists():
            messagebox.showerror("Path not found", f"{path} does not exist.")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def _on_close(self) -> None:
        """Detach the UI log handler and close the root window cleanly."""

        if self.current_controller is not None:
            self.current_controller.request_stop()
        self.hover_tooltip.hide()
        if self.log_handler in self.root_logger.handlers:
            self.root_logger.removeHandler(self.log_handler)
        self.root.destroy()


def launch_desktop_app(args: Any) -> int:
    """Start the guided Tkinter workbench."""

    return DesktopWorkbench(args).run()
