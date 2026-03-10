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
        self.window.geometry(f"+{x + 16}+{y + 16}")
        self.window.deiconify()

    def hide(self) -> None:
        """Hide the tooltip until the next hover event."""

        if self.window is not None:
            self.window.withdraw()


class DesktopWorkbench:
    """Tkinter workbench for guided configuration and result inspection."""

    MULTILINE_FIELDS = {
        "research_topic": ("Research brief", 3),
        "research_question": ("Research question", 3),
        "review_objective": ("Review objective", 3),
        "search_keywords": ("Search keywords (comma-separated)", 3),
        "inclusion_criteria": ("Inclusion criteria (; separated)", 3),
        "exclusion_criteria": ("Exclusion criteria (; separated)", 3),
        "banned_topics": ("Banned topics (; separated)", 2),
        "excluded_title_terms": ("Excluded title terms (; separated)", 2),
        "analysis_passes": ("Analysis passes (one per line)", 4),
    }

    ENUM_FIELDS = {
        "boolean_operators": ["AND", "OR", "NOT"],
        "discovery_strategy": ["precise", "balanced", "broad"],
        "pdf_download_mode": ["all", "relevant_only"],
        "llm_provider": ["auto", "heuristic", "openai_compatible", "ollama", "huggingface_local"],
        "decision_mode": ["strict", "triage"],
        "run_mode": ["collect", "analyze"],
        "verbosity": ["quiet", "normal", "verbose", "debug"],
        "huggingface_task": ["text-generation"],
        "huggingface_device": ["auto", "cpu", "cuda"],
        "huggingface_dtype": ["auto", "float16", "bfloat16", "float32"],
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
        "pages_to_retrieve": "Pages per source",
        "results_per_page": "Results per page",
        "max_discovered_records": "Max discovered records",
        "min_discovered_records": "Min discovered records",
        "year_range_start": "Year start",
        "year_range_end": "Year end",
        "max_papers_to_analyze": "Max papers to analyze",
        "skip_discovery": "Skip discovery",
        "relevance_threshold": "Relevance threshold",
        "maybe_threshold_margin": "Maybe margin",
        "full_text_max_chars": "Full-text chars",
        "request_timeout_seconds": "Request timeout (s)",
        "title_similarity_threshold": "Title similarity threshold",
        "openai_base_url": "OpenAI base URL",
        "openai_model": "OpenAI model",
        "openai_api_key": "OpenAI API key",
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

    HANDBOOK_GUIDES = {
        "guide:outputs": (
            "Guide",
            "Where CSV, JSON, SQLite, and PDFs go",
            "Use the 'PDFs and Outputs' section in Settings. There you can turn CSV, JSON, Markdown, and SQLite "
            "exports on or off, choose whether PDFs should be downloaded, and set the data, papers, results, "
            "database, and relevant-PDF directories. If you only want PDFs for accepted papers, enable "
            "'Download PDFs' and set 'PDF download mode' to 'relevant_only'.",
        ),
        "guide:models": (
            "Guide",
            "How to choose the AI model",
            "Use the 'Screening and Models' section. 'LLM provider' decides whether the run uses heuristic scoring, "
            "OpenAI-compatible APIs, Ollama, or a local Hugging Face model. Then configure the matching model fields "
            "such as OpenAI model, Ollama model, or HF model. Thresholds and decision mode in the same section "
            "control how strict the keep/exclude decisions are.",
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
            "Optional multi-pass screening plan, one pass per line. This lets you chain a fast first pass with a "
            "deeper second pass, each with its own provider and threshold."
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
        "openai_model": "Hosted model name used when the OpenAI-compatible provider is selected.",
        "openai_api_key": "Credential for the OpenAI-compatible provider. It is masked in the UI and never logged verbatim.",
        "ollama_base_url": "Local or remote Ollama server URL, usually http://localhost:11434.",
        "ollama_model": "Installed Ollama model tag used for local screening, for example qwen3:8b.",
        "ollama_api_key": "Optional Ollama gateway key if your endpoint requires authentication.",
        "llm_temperature": (
            "Sampling temperature for supported LLM backends. Lower values are more deterministic, while higher values "
            "allow more variation in the screening explanation."
        ),
        "huggingface_model": (
            "Local Hugging Face model used for screening. The default Qwen/Qwen3-14B is the balanced local choice for "
            "this project, but you can replace it with any compatible instruct model."
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
        "output_csv": "Write tabular review outputs such as papers.csv, included_papers.csv, and excluded_papers.csv.",
        "output_json": "Write machine-readable JSON outputs such as ranked results and PRISMA-style flow summaries.",
        "output_markdown": "Write the generated literature review summary and other Markdown reports.",
        "output_sqlite_exports": (
            "Write included and excluded export databases in addition to the main runtime SQLite database."
        ),
        "data_dir": "Base directory used for persistent runtime data such as SQLite files and cached artifacts.",
        "papers_dir": "Directory where downloaded PDFs and paper-related files are stored by default.",
        "relevant_pdfs_dir": "Dedicated directory for PDFs that passed the final screening threshold.",
        "results_dir": "Directory where reports, CSV files, JSON outputs, and summary artifacts are written.",
        "database_path": "Path to the main SQLite database used for metadata, screening state, and resume support.",
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
        self.treeviews: dict[str, ttk.Treeview] = {}
        self.table_frames: dict[str, ttk.Frame] = {}
        self.outputs_tree: ttk.Treeview | None = None
        self.handbook_tree: ttk.Treeview | None = None
        self.handbook_text: scrolledtext.ScrolledText | None = None
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

        canvas = tk.Canvas(self.settings_tab)
        scrollbar = ttk.Scrollbar(self.settings_tab, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas, padding=12)
        scrollable.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        row = 0
        ttk.Label(
            scrollable,
            text=(
                "Every CLI-relevant runtime setting is exposed here. Hover fields for a quick explanation or use the "
                "Handbook tab for a searchable reference."
            ),
            wraplength=1100,
            justify="left",
        ).grid(row=row, column=0, sticky="w", padx=6, pady=(0, 8))
        row += 1
        for section_name, field_names in self.GROUPS:
            frame = ttk.LabelFrame(scrollable, text=section_name, padding=10)
            frame.grid(row=row, column=0, sticky="nsew", padx=6, pady=6)
            frame.columnconfigure(1, weight=1)
            self._bind_hover_help(frame, self.SECTION_HELP_TEXTS.get(section_name, section_name))
            inner_row = 0
            for field_name in field_names:
                label = self.LABELS.get(field_name, field_name.replace("_", " ").title())
                help_text = self._help_text_for_field(field_name)
                if field_name in self.MULTILINE_FIELDS:
                    _, height = self.MULTILINE_FIELDS[field_name]
                    label_widget = ttk.Label(frame, text=label)
                    label_widget.grid(row=inner_row, column=0, sticky="nw", padx=4, pady=4)
                    self._bind_hover_help(label_widget, help_text)
                    widget = tk.Text(frame, height=height, wrap="word")
                    widget.grid(row=inner_row, column=1, sticky="ew", padx=4, pady=4)
                    self.text_widgets[field_name] = widget
                    self._bind_hover_help(widget, help_text)
                elif field_name in BOOLEAN_FIELD_DEFAULTS:
                    variable = tk.BooleanVar(value=BOOLEAN_FIELD_DEFAULTS[field_name])
                    widget = ttk.Checkbutton(frame, text=label, variable=variable)
                    widget.grid(row=inner_row, column=0, columnspan=2, sticky="w", padx=4, pady=4)
                    self.scalar_vars[field_name] = variable
                    self._bind_hover_help(widget, help_text)
                else:
                    label_widget = ttk.Label(frame, text=label)
                    label_widget.grid(row=inner_row, column=0, sticky="w", padx=4, pady=4)
                    self._bind_hover_help(label_widget, help_text)
                    if field_name in self.ENUM_FIELDS:
                        variable = tk.StringVar(value=str(SCALAR_FIELD_DEFAULTS.get(field_name, "")))
                        widget = ttk.Combobox(frame, textvariable=variable, values=self.ENUM_FIELDS[field_name], state="readonly")
                        widget.grid(row=inner_row, column=1, sticky="ew", padx=4, pady=4)
                    else:
                        default_value = SCALAR_FIELD_DEFAULTS.get(field_name, "")
                        variable = tk.StringVar(value=str(default_value))
                        entry_kwargs: dict[str, Any] = {"textvariable": variable}
                        if "key" in field_name.lower() and "mail" not in field_name.lower():
                            entry_kwargs["show"] = "*"
                        if field_name in self.PATH_FIELD_MODES:
                            entry_frame = ttk.Frame(frame)
                            entry_frame.grid(row=inner_row, column=1, sticky="ew", padx=4, pady=4)
                            entry_frame.columnconfigure(0, weight=1)
                            widget = ttk.Entry(entry_frame, **entry_kwargs)
                            widget.grid(row=0, column=0, sticky="ew")
                            browse_button = ttk.Button(
                                entry_frame,
                                text="Browse",
                                command=lambda name=field_name, var=variable: self._browse_for_field(name, var),
                            )
                            browse_button.grid(row=0, column=1, padx=(6, 0))
                            self._bind_hover_help(browse_button, help_text)
                        else:
                            widget = ttk.Entry(frame, **entry_kwargs)
                            widget.grid(row=inner_row, column=1, sticky="ew", padx=4, pady=4)
                    self.scalar_vars[field_name] = variable
                    self._bind_hover_help(widget, help_text)
                inner_row += 1
            row += 1

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
            widget.delete("1.0", tk.END)
            widget.insert("1.0", str(values.get(field_name, "")))
        for field_name, variable in self.scalar_vars.items():
            variable.set(values.get(field_name, variable.get()))

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
