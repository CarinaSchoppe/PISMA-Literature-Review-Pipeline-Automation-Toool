# Configuration Reference

This reference describes the runtime configuration surface for the PRISMA Literature Review Pipeline.

The same configuration can be supplied through:

- JSON config files
- CLI flags
- the guided desktop GUI

The GUI and CLI map to the same validated runtime model. This document focuses on the meaning of the settings rather than the screen layout.

## Configuration Model

The runtime is centered on one validated research-review configuration plus nested provider settings.

In practice that means:

- the JSON config file uses the same logical field names described here
- CLI flags override those values for a specific run
- the GUI edits those values interactively and can save them as profiles

## Review Brief Settings

These fields define the screening concept used in discovery, semantic topic matching, and AI screening.

`research_topic`

- Main topic or review area.
- Example: `AI governance in healthcare decision support`

`research_question`

- Explicit research question that screening should answer.
- Example: `How are large language models evaluated for clinical decision support and governance risk?`

`review_objective`

- Explains the intended review output or use case.
- Example: `Build a shortlist of empirical evaluation studies and recent review papers`

`search_keywords`

- Search terms used to generate source queries.
- Supported separators:
  - comma
  - semicolon
  - newline
- Example values:
  - `AI governance, generative AI, decision support`
  - `AI governance; generative AI; decision support`

`boolean_operators`

- Optional Boolean connector or expression used while building search queries.
- Typical values:
  - `AND`
  - `OR`
  - a short custom expression

`inclusion_criteria`

- Positive screening rules.
- Example:
  - `empirical evaluation; systematic review; healthcare AI`

`exclusion_criteria`

- Rules that should exclude papers even if the topic appears similar.
- Example:
  - `non-scholarly commentary; marketing material; undergraduate coursework`

`banned_topics`

- Hard thematic bans that can drive exclusion.
- Example:
  - `agricultural irrigation; crop yield`

`excluded_title_terms`

- Title markers that should usually be dropped before deeper screening.
- Example:
  - `correction; erratum; editorial; retraction`

## Discovery Settings

These settings control where the pipeline searches and how broad the search is.

### Source Toggles

Live API sources:

- `openalex_enabled`
- `semantic_scholar_enabled`
- `crossref_enabled`
- `springer_enabled`
- `arxiv_enabled`
- `include_pubmed`
- `europe_pmc_enabled`
- `core_enabled`

Live HTML source:

- `google_scholar_enabled`

Manual import and offline sources:

- `fixture_data_path`
- `manual_source_path`
- `google_scholar_import_path`
- `researchgate_import_path`

### Discovery Breadth

`pages_to_retrieve`

- Number of pages or batches requested from each API-style source.

`results_per_page`

- Number of records requested per source page.

`discovery_strategy`

- `precise`
  - fewer query variants, narrower recall
- `balanced`
  - default trade-off between recall and cost
- `broad`
  - more query variants and broader recall

`year_range_start`

- Lower year boundary for filtering.

`year_range_end`

- Upper year boundary for filtering.

`max_discovered_records`

- Hard cap on the deduplicated discovery set after merge and deduplication.

`min_discovered_records`

- Minimum deduplicated discovery count required before screening continues.

`max_papers_to_analyze`

- Separate cap on the papers sent into screening.

`skip_discovery`

- Reuse stored papers for the current query context instead of running discovery again.

`citation_snowballing_enabled`

- Enables backward and forward citation expansion.

## Google Scholar Page Depth

These settings are specific to the bounded Google Scholar traversal path.

`google_scholar_pages`

- Number of result pages to process.
- Validated against `google_scholar_page_min` and `google_scholar_page_max`
- Higher values increase retrieval breadth and runtime.

`google_scholar_page_min`

- Lower validation bound for `google_scholar_pages`.
- Default: `1`
- Useful when an operator profile should never run a shallow Scholar crawl by mistake.

`google_scholar_page_max`

- Upper validation bound for `google_scholar_pages`.
- Default: `100`
- Useful when a shared config should prevent unexpectedly expensive Scholar traversals.

`google_scholar_results_per_page`

- Expected page size used when calculating offsets.

`google_scholar_calls_per_second`

- Throttle for Scholar page requests.

Behavior summary:

- each query is processed page by page
- partial page failures are logged and skipped
- collected results are deduplicated afterward
- force-stop requests are honored between page boundaries

## Guided GUI Defaults

These settings are persisted with saved GUI profiles so the desktop workbench opens in a predictable state.

`ui_settings_mode`

- Controls the default density of the `Settings` shell.
- Supported values:
  - `compact`
  - `advanced`
- `compact` keeps longer helper sections collapsed by default and fits better on smaller windows
- `advanced` keeps more section guidance visible for deeper orientation

`ui_show_advanced_settings`

- Controls whether advanced settings pages are visible immediately on startup.
- `true`
  - advanced runtime pages open without an extra toggle
- `false`
  - the workbench starts in the simpler view and reveals advanced pages only when requested

Practical GUI behavior:

- these fields control the startup state of the workbench
- the workbench also applies responsive compact-window behavior automatically when the window is too small for the larger overview panels
- the large workspace overview and the large settings overview can both be collapsed manually at runtime

## Local MiniLM Semantic Topic Prefilter

This is the local CPU-friendly semantic relevance layer.

`topic_prefilter_enabled`

- Enables the MiniLM semantic gate.
- Reuses one cached local model instance per process so repeated paper scoring avoids unnecessary reloads.

`topic_prefilter_filter_low_relevance`

- Automatically excludes `LOW_RELEVANCE` papers when enabled.

`topic_prefilter_high_threshold`

- Default threshold for `HIGH_RELEVANCE`
- Default behavior:
  - `>= 0.75` -> `HIGH_RELEVANCE`

`topic_prefilter_review_threshold`

- Default threshold for `REVIEW`
- Default behavior:
  - `>= 0.55 and < 0.75` -> `REVIEW`
  - `< 0.55` -> `LOW_RELEVANCE`

`topic_prefilter_text_mode`

- Controls which paper text goes into semantic matching:
  - `title_only`
  - `title_abstract`
  - `title_abstract_full_text`

`topic_prefilter_max_chars`

- Maximum amount of paper text used for local semantic matching.
- Keep this moderate on CPU-only machines to avoid wasteful embedding work on long full-text excerpts.

`topic_prefilter_model`

- Local sentence-transformer model identifier.
- Default:
  - `sentence-transformers/all-MiniLM-L6-v2`

Outputs stored for explainability include:

- similarity score
- classification label
- used text sections
- keyword overlap
- reason summary

## AI Screening Settings

These settings control the heavier screening and ranking passes.

`llm_provider`

- Top-level screening provider.
- Supported values:
  - `auto`
  - `heuristic`
  - `openai_compatible`
  - `gemini`
  - `ollama`
  - `huggingface_local`

`relevance_threshold`

- Main score threshold from `0` to `100`.

`decision_mode`

- `strict`
  - keep or exclude only
- `triage`
  - allows `maybe`

`maybe_threshold_margin`

- Margin below the main threshold that still qualifies as `maybe` in triage mode.

`analyze_full_text`

- Use extracted PDF text when available.

`full_text_max_chars`

- Cap the text volume passed into screening.

`analysis_passes`

- Ordered pass chain for multi-model screening.
- Each pass can define:
  - name
  - provider
  - threshold
  - decision mode
  - maybe margin
  - model override
  - minimum previous-pass score

## Provider Settings

### OpenAI-compatible

- `openai_api_key`
- `openai_base_url`
- `openai_model`

### Gemini

- `gemini_api_key`
- `gemini_base_url`
- `gemini_model`

### Ollama

- `ollama_base_url`
- `ollama_model`
- `ollama_api_key`

### Local Hugging Face

- `huggingface_model`
- `huggingface_task`
- `huggingface_device`
- `huggingface_dtype`
- `huggingface_max_new_tokens`
- `huggingface_cache_dir`
- `huggingface_trust_remote_code`

### Shared generation setting

- `llm_temperature`

## Output And Storage Settings

`download_pdfs`

- Enables PDF acquisition.

`pdf_download_mode`

- `all`
- `relevant_only`

`output_csv`

- Write CSV exports.

`output_json`

- Write JSON exports.

`output_markdown`

- Write Markdown exports.

`output_sqlite_exports`

- Write included and excluded SQLite export databases.

Path settings:

- `data_dir`
- `papers_dir`
- `relevant_pdfs_dir`
- `results_dir`
- `database_path`
- `log_file_path`

Practical PDF routing:

- `all` mode stores PDFs under `papers_dir`
- `relevant_only` can route kept PDFs to `relevant_pdfs_dir`
- use the same directory for both if you want one shared PDF folder

## Runtime, Parallelism, And Logging

`run_mode`

- `collect`
- `analyze`

`verbosity`

- `normal`
- `verbose`
- `ultra_verbose`

Compatibility note:

- `debug` and `quiet` are still accepted by the parser and config model
- the primary documented operating modes remain `normal`, `verbose`, and `ultra_verbose`

`max_workers`

- Global worker fallback.

`discovery_workers`

- Discovery-stage worker override.

`io_workers`

- PDF and full-text preparation worker override.

`screening_workers`

- Screening worker override.

`request_timeout_seconds`

- HTTP timeout.

`resume_mode`

- Reuse cached screening and skip repeated work where valid.

`reset_query_records`

- Delete previously stored paper rows for the active query before a rerun.

`clear_screening_cache`

- Delete cached screening results for the current screening context.

`disable_progress_bars`

- Suppress tqdm progress bars.

`title_similarity_threshold`

- Title-similarity fallback threshold used during deduplication.

Detailed logging toggles:

- `log_http_requests`
- `log_http_payloads`
- `log_llm_prompts`
- `log_llm_responses`
- `log_screening_decisions`

## HTTP Cache, Retry, And Rate Limiting

General HTTP controls:

- `http_cache_enabled`
- `http_cache_dir`
- `http_cache_ttl_seconds`
- `http_retry_max_attempts`
- `http_retry_base_delay_seconds`
- `http_retry_max_delay_seconds`

Semantic Scholar rate-limit controls:

- `semantic_scholar_calls_per_second`
- `semantic_scholar_max_requests_per_minute`
- `semantic_scholar_request_delay_seconds`
- `semantic_scholar_retry_attempts`
- `semantic_scholar_retry_backoff_strategy`
- `semantic_scholar_retry_backoff_base_seconds`

Backoff behavior:

- proactive throttling runs before requests are sent
- `Retry-After` is respected when present
- bounded exponential backoff is the default fallback
- exhausted retry paths fail cleanly and log the reason

Per-source request pacing is also available for:

- OpenAlex
- Crossref
- Springer
- arXiv
- PubMed
- Europe PMC
- CORE
- Unpaywall
- Google Scholar

## Partial Reruns And Incremental Reporting

`partial_rerun_mode`

- `off`
- `reporting_only`
- `screening_and_reporting`
- `pdfs_screening_reporting`

`incremental_report_regeneration`

- Skip rewriting unchanged report artifacts.

`enable_async_network_stages`

- Use the optional async orchestration layer for eligible network-heavy stages.

`pdf_batch_size`

- Size of each PDF processing batch.

## Coverage Scope

Project coverage is intentionally split into two modes:

- production-code coverage
  - the default configuration omits `tests/*`
  - this is the enforced release gate
- whole-tree reference coverage
  - includes test modules too
  - useful when you explicitly want every Python file in one report

That is why a plain `python -m coverage report` usually shows production files only unless the run was created with `--include-tests`.

## Environment Variables

Common environment variables:

- `UNPAYWALL_EMAIL`
- `CROSSREF_MAILTO`
- `SEMANTIC_SCHOLAR_API_KEY`
- `SPRINGER_API_KEY`
- `CORE_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `GEMINI_API_KEY`
- `GOOGLE_API_KEY`
- `GEMINI_BASE_URL`
- `GEMINI_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_API_KEY`
- `HF_MODEL_ID`
- `HF_TASK`
- `HF_DEVICE`
- `HF_DTYPE`
- `HF_MAX_NEW_TOKENS`
- `HF_HOME`
- `TRANSFORMERS_CACHE`
- `HF_TRUST_REMOTE_CODE`
- `LLM_TEMPERATURE`

## Recommended Configuration Workflow

1. Start in the GUI and save a profile.
2. Move the stable setup into a JSON config file for repeatable runs.
3. Use CLI overrides only for temporary experiments.
4. Keep `run_config.json` with the output artifacts for reproducibility.
