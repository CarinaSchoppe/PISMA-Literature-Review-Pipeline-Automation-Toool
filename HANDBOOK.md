# Project Handbook

This handbook is the operator guide for the PRISMA Literature Review Pipeline.
All user-facing documentation, GUI labels, GUI help text, and CLI prompts are intentionally written in English only.

Use it when you want one place that explains:

- what each setting does
- where the setting lives in the GUI
- which CLI flag matches it
- how provider selection and pass chaining work
- where outputs are written
- how stop, resume, verbose logging, and PDF routing behave
- how type-checking, CI, coverage, and benchmark tooling fit into the workflow

The README stays the short project overview. This handbook is the practical reference.

For the planned future feature direction, see [ROADMAP.md](ROADMAP.md).

## Core Idea

The pipeline is built for systematic literature discovery and AI-assisted screening with one shared runtime configuration.

That same configuration can be edited through:

- the guided desktop GUI
- the classic interactive console wizard
- direct CLI flags
- a JSON config file

The GUI is not separate logic. It edits the same validated `ResearchConfig` that the CLI uses.

## Start Modes

Launcher menu:

```powershell
py -3 main.py
```

Direct GUI:

```powershell
py -3 main.py --ui
```

Classic text wizard:

```powershell
py -3 main.py --wizard
```

Headless scripted run:

```powershell
py -3 main.py --config-file path\to\run_config.json
```

## Workflow

The pipeline order is:

```text
input -> discovery -> deduplication -> database storage -> citation expansion -> pdf enrichment -> AI screening -> scoring -> ranking -> report generation
```

Two run modes exist:

- `collect`: only discovery, deduplication, storage, enrichment, and export
- `analyze`: full workflow including AI screening and review summary generation

## GUI Layout

The desktop workbench is split into tabs and settings pages.

Visual defaults:

- light, high-contrast theme intended to keep long review sessions readable
- accent primary action button for `Start Run`
- dedicated danger styling for `Force Stop`
- muted secondary actions and cleaner notebook/table styling for easier scanning

Main tabs:

- `Settings`
- `Run Log`
- `All Papers`
- `Included`
- `Excluded`
- `Outputs`
- `Charts`
- `Run History`
- `Screening Audit`
- `Handbook`

Settings pages:

- `Review Setup`
- `Discovery`
- `AI Screening`
- `Connections and Keys`
- `Storage and Output`
- `Advanced Runtime`

Settings layout:

- the left rail is the primary page navigation for the settings workflow
- the center pane keeps the current settings page in focus
- the right inspector contains `Find`, `Quick Edit`, `Guides`, and `Summary` tabs so secondary tools do not overwhelm the main form
- the three settings panes are resizable, so you can give more space to the editor or inspector when needed
- the inspector `Summary` tab shows the current model setup, provider health, grouped path summaries, and an export preview before a run starts
- the `Quick Edit` tab keeps grouped output toggles and grouped path controls together so storage changes stay easier to review

Important visibility behavior:

- each settings page is vertically scrollable
- the `Quick Edit` inspector tab is also scrollable when its cards exceed the visible window height
- the `Summary` inspector tab is also scrollable
- `Compact` settings mode collapses longer section descriptions to reduce visual density
- `Advanced` settings mode restores the full section helper text on the settings pages
- `Connections and Keys` is the dedicated page for provider URLs, API keys, Crossref mailto, and Unpaywall email
- `Advanced Runtime` stays hidden until `Show advanced settings` is enabled or a search jump opens one of its fields
- hover help, handbook entries, and focus help use expanded English explanations that describe the purpose of a setting, what happens when the setting is enabled or disabled, and a practical example where useful

Toolbar actions:

- `Start Run`: run discovery and analysis using the current form values
- `Analyze Stored Results`: skip new discovery and analyze papers that already exist in the active database
- `Force Stop`: request a controlled stop

Result inspection tabs:

- `Outputs`: artifact browser with file summaries, planned export preview, `Open Selected`, and `Open Parent Folder`
- `Charts`: lightweight on-device chart preview for screening decisions and source mix
- `Run History`: persistent JSON-backed record of recent runs, including status, topic, and artifact paths
- `Screening Audit`: per-paper explanations, retain reasons, exclusion reasons, and extracted passages from `papers.csv`

Pass-chain builder:

- the pass builder is a visual dialog rather than a raw text field
- each pass can set:
  - pass name
  - provider
  - decision mode
  - threshold
  - maybe margin
  - model override
  - minimum previous-pass score required to enter the pass
- the builder also shows:
  - a chain overview on the left
  - a selected-pass preview on the right
  - a `Duplicate Pass` action for quick branching

Important stop behavior:

- `Force Stop` is best-effort and controlled
- the app stops after the current request, worker task, or model call reaches a safe boundary
- it is not a process kill switch

## How Settings Map Between GUI And CLI

Most runtime fields map directly:

- config field `results_dir` -> CLI flag `--results-dir`
- config field `database_path` -> CLI flag `--database-path`
- config field `log_http_requests` -> CLI flag `--log-http-requests`

Boolean fields usually support both forms:

- `--download-pdfs`
- `--no-download-pdfs`

The GUI exposes the same underlying settings as checkboxes, dropdowns, sliders, spinboxes, path pickers, resizable panes, scrollable settings pages, a scrollable quick-edit panel, and a search box that can reveal hidden advanced pages automatically.

If in doubt, the authoritative sources are:

- the GUI settings pages
- `py -3 main.py --help`
- `config.py`

## Settings Reference

### Review Setup

These fields define the research brief used in search, scoring, and explainability.

`research_topic`

- Main topic or domain of the review.
- GUI: `Review Setup`
- CLI: `--topic`

`research_question`

- Explicit question the screening logic should answer.
- Helps LLM and heuristic scoring stay aligned with the review goal.
- GUI: `Review Setup`
- CLI: `--research-question`

`review_objective`

- Describes the intended output or review purpose.
- Useful for methodological framing.
- GUI: `Review Setup`
- CLI: `--review-objective`

`inclusion_criteria`

- Positive screening rules.
- Semicolon-separated in CLI.
- GUI: `Review Setup`
- CLI: `--inclusion-criteria`

`exclusion_criteria`

- Rules that push a paper out even if the topic looks similar.
- GUI: `Review Setup`
- CLI: `--exclusion-criteria`

`banned_topics`

- Hard topic bans.
- If matched strongly, a paper can be excluded before deeper scoring.
- GUI: `Review Setup`
- CLI: `--banned-topics`

`excluded_title_terms`

- Hard title markers such as `correction`, `erratum`, `editorial`, `retraction`.
- Useful for filtering non-primary literature.
- GUI: `Review Setup`
- CLI: `--excluded-title-terms`

`search_keywords`

- Comma-separated keyword list used to build source queries.
- GUI: `Review Setup`
- CLI: `--keywords`

`boolean_operators`

- Optional Boolean connector or expression, usually `AND` or `OR`.
- GUI: `Review Setup`
- CLI: `--boolean`

### Discovery

These settings control where and how metadata is collected.

Source toggles:

- `openalex_enabled` -> `--openalex-enabled` / `--no-openalex-enabled`
- `semantic_scholar_enabled` -> `--semantic-scholar-enabled` / `--no-semantic-scholar-enabled`
- `crossref_enabled` -> `--crossref-enabled` / `--no-crossref-enabled`
- `springer_enabled` -> `--springer-enabled` / `--no-springer-enabled`
- `arxiv_enabled` -> `--arxiv-enabled` / `--no-arxiv-enabled`
- `include_pubmed` -> `--include-pubmed` / `--no-include-pubmed`
- `europe_pmc_enabled` -> `--europe-pmc-enabled` / `--no-europe-pmc-enabled`
- `core_enabled` -> `--core-enabled` / `--no-core-enabled`

What each source is good for:

- `OpenAlex`: broad academic metadata, references, citations, strong for snowballing
- `Semantic Scholar`: useful citation and abstract metadata, but public quota can rate-limit
- `Crossref`: broad DOI and publisher metadata
- `Springer`: official Springer Nature metadata source, requires API key
- `arXiv`: preprint-heavy discovery, useful for AI/ML topics
- `PubMed`: biomedical and clinical coverage
- `Europe PMC`: biomedical and life-science search, useful when you want another strong biomedical index beyond PubMed
- `CORE`: open-access and repository-heavy discovery, useful for institutional repositories and broader full-text recall

Source-specific credentials and throttles:

- `springer_api_key` -> `--springer-api-key`
- `core_api_key` -> `--core-api-key`
- `crossref_mailto` -> `--crossref-mailto`
- `unpaywall_email` -> `--unpaywall-email`

Practical note:

- `CORE` works without a key in some environments, but a configured key is the safer production setup for stable access and quota handling.
- `Europe PMC` does not require an API key in this project, but you can still tune its request rate with `europe_pmc_calls_per_second`.

Import-only source paths:

- `fixture_data_path` -> `--fixture-data`
- `manual_source_path` -> `--manual-source-path`
- `google_scholar_import_path` -> `--google-scholar-import-path`
- `researchgate_import_path` -> `--researchgate-import-path`

These are for deterministic offline testing or bringing in exported metadata from sources that are not queried live.

Result volume controls:

`pages_to_retrieve`

- Number of pages or batches to request per source.
- GUI: `Discovery`
- CLI: `--pages`

`results_per_page`

- Batch size per source request.
- Lower values can reduce burstiness and rate-limit pressure.
- GUI: `Discovery`
- CLI: `--results-per-page`

`discovery_strategy`

- `precise`: narrower search, fewer variants
- `balanced`: default tradeoff
- `broad`: more query variants and broader recall
- GUI: `Discovery`
- CLI: `--discovery-strategy`

Year limits:

- `year_range_start` -> `--year-start`
- `year_range_end` -> `--year-end`

Global discovery gates:

`max_discovered_records`

- Hard cap on the deduplicated record set after discovery.
- Useful when you want broad search but bounded cost.
- GUI: `Discovery`
- CLI: `--max-discovered-records`

`min_discovered_records`

- Hard minimum required to continue into screening.
- If the merged deduplicated result set stays below this number, the run stops before analysis.
- GUI: `Discovery`
- CLI: `--min-discovered-records`

`max_papers_to_analyze`

- Caps how many papers from the discovered set go into screening.
- Separate from discovery cap.
- GUI: `Discovery`
- CLI: `--max-papers`

`skip_discovery`

- Reuse already stored papers for the current query context.
- This powers the `Analyze Stored Results` action in the GUI.
- GUI: `Discovery` and toolbar shortcut
- CLI: `--skip-discovery`

`citation_snowballing_enabled`

- Enables backward and forward citation expansion.
- Works best with OpenAlex enabled.
- GUI: `Discovery`
- CLI: `--citation-snowballing`

`http_cache_enabled`

- Enables the persistent source-response cache for eligible GET requests.
- `Yes` means repeated discovery calls can reuse cached responses until the TTL expires.
- `No` means every request is fetched fresh from the upstream source.
- Example:
  Use `Yes` when you are tuning screening thresholds against the same discovery query and want to avoid re-hitting the same provider pages.
- GUI: `Discovery`
- CLI: `--http-cache-enabled` / `--no-http-cache-enabled`

`http_cache_dir`

- Directory where cached source responses are stored.
- Example:
  `data/http_cache`
- GUI: `Discovery`
- CLI: `--http-cache-dir`

`http_cache_ttl_seconds`

- Maximum age of cached responses before they must be refreshed.
- Higher values favor speed and fewer network calls.
- Lower values favor fresher source data.
- Example:
  `86400` means the cache is valid for one day.
- GUI: `Discovery`
- CLI: `--http-cache-ttl-seconds`

`http_retry_max_attempts`

- Maximum number of request attempts when the HTTP helper encounters `429` or another eligible retry path.
- Example:
  `4` means the initial request plus up to three additional attempts.
- GUI: `Discovery`
- CLI: `--http-retry-max-attempts`

`http_retry_base_delay_seconds`

- Base delay for bounded exponential backoff when `Retry-After` is missing.
- Example:
  `1.0` means the fallback retry delays are `1`, then `2`, then `4` seconds unless capped.
- GUI: `Discovery`
- CLI: `--http-retry-base-delay-seconds`

`http_retry_max_delay_seconds`

- Upper bound for a single retry delay, even if the provider asks for a larger wait.
- Example:
  `30` keeps retry waits below thirty seconds per attempt.
- GUI: `Discovery`
- CLI: `--http-retry-max-delay-seconds`

### AI Screening

These settings control scoring, pass chains, and model behavior.

`llm_provider`

- Top-level provider mode for single-pass or default behavior.
- Allowed values:
  - `auto`
  - `heuristic`
  - `openai_compatible`
  - `gemini`
  - `ollama`
  - `huggingface_local`
- GUI: `AI Screening`
- CLI: `--llm-provider`

`relevance_threshold`

- Main threshold from `0` to `100`.
- Above threshold means retain in `strict` mode.
- GUI: slider in `AI Screening`
- CLI: `--threshold`

`decision_mode`

- `strict`: only keep or exclude
- `triage`: allows `maybe` inside a configurable margin
- GUI: `AI Screening`
- CLI: `--decision-mode`

`maybe_threshold_margin`

- Only used in `triage`.
- Example: threshold `85` with margin `10` means `75-84.99` can become `maybe`.
- GUI: slider in `AI Screening`
- CLI: `--maybe-threshold-margin`

`analyze_full_text`

- If PDFs exist and full-text extraction succeeds, screening can use text beyond title and abstract.
- GUI: `AI Screening`
- CLI: `--analyze-full-text`

`full_text_max_chars`

- Caps how much extracted text goes into screening.
- GUI: `AI Screening`
- CLI: `--full-text-max-chars`

`analysis_passes`

- Sequential pass chain for multi-model or multi-threshold analysis.
- GUI: `Edit Pass Chain`
- CLI: repeatable `--analysis-pass`

Each pass can define:

- `name`
- `llm_provider`
- `threshold`
- `decision_mode`
- `maybe_threshold_margin`
- `model_name`
- `min_input_score`
- `enabled`

`min_input_score` means:

- do not run this pass unless the previous pass score was at least this value
- useful for skipping expensive models when a cheap first pass already gives a very low score

Example chain:

```text
fast|huggingface_local|65|strict|8|Qwen/Qwen3-14B|0
deep|gemini|82|triage|10|gemini-2.5-flash|65
final|openai_compatible|88|strict|5|gpt-5.4|82
```

### Provider And Model Settings

These are in the GUI under `AI Screening`, plus quick-access controls in `Settings`.

OpenAI-compatible:

- `openai_api_key` -> `--openai-api-key`
- `openai_base_url` -> `--openai-base-url`
- `openai_model` -> `--openai-model`

Gemini:

- `gemini_api_key` -> `--gemini-api-key`
- `gemini_base_url` -> `--gemini-base-url`
- `gemini_model` -> `--gemini-model`

Ollama:

- `ollama_base_url` -> `--ollama-base-url`
- `ollama_model` -> `--ollama-model`
- `ollama_api_key` -> `--ollama-api-key`

Local Hugging Face:

- `huggingface_model` -> `--huggingface-model`
- `huggingface_task` -> `--huggingface-task`
- `huggingface_device` -> `--huggingface-device`
- `huggingface_dtype` -> `--huggingface-dtype`
- `huggingface_max_new_tokens` -> `--huggingface-max-new-tokens`
- `huggingface_cache_dir` -> `--huggingface-cache-dir`
- `huggingface_trust_remote_code` -> `--huggingface-trust-remote-code`

Shared model setting:

- `llm_temperature` -> `--llm-temperature`

Recommended practical defaults:

- hosted strongest path: OpenAI-compatible with `gpt-5.4`
- Google ecosystem path: Gemini with `gemini-2.5-flash`
- local easy path: Ollama with `qwen3:8b`
- local open-weight path: Hugging Face with `Qwen/Qwen3-14B`

### Storage And Output

These settings control where files go and which export bundles are written.

`download_pdfs`

- Enables file download for open-access PDFs.
- GUI: `Storage and Output`
- CLI: `--download-pdfs`

`pdf_download_mode`

- `all`: download every eligible PDF
- `relevant_only`: only download papers that survive screening
- GUI: `Storage and Output`
- CLI: `--pdf-download-mode`

`output_csv`

- Write CSV exports.
- GUI: `Storage and Output`
- CLI: `--output-csv`

`output_json`

- Write JSON exports.
- GUI: `Storage and Output`
- CLI: `--output-json`

`output_markdown`

- Write Markdown summary output.
- GUI: `Storage and Output`
- CLI: `--output-markdown`

`output_sqlite_exports`

- Write included and excluded SQLite export databases.
- GUI: `Storage and Output`
- CLI: `--output-sqlite-exports`

Path settings:

- `data_dir` -> `--data-dir`
- `papers_dir` -> `--papers-dir`
- `relevant_pdfs_dir` -> `--relevant-pdfs-dir`
- `results_dir` -> `--results-dir`
- `database_path` -> `--database-path`

How PDF routing works:

- if `pdf_download_mode=all`, PDFs go under `papers_dir`
- if `pdf_download_mode=relevant_only`, kept papers can go to `relevant_pdfs_dir`
- if you want all PDFs in one folder, set `relevant_pdfs_dir` to the same path as `papers_dir`

What the SQLite files mean:

- `database_path`: main runtime database used during the run
- `included_papers.db` and `excluded_papers.db`: optional decision export databases in the results area

### Runtime And Logs

`run_mode`

- `collect` or `analyze`
- GUI: `Advanced Runtime`
- CLI: `--run-mode`

`verbosity`

- `quiet`: minimal console noise
- `normal`: stage boundaries and counts
- `verbose`: source activity, screening activity, output writes
- `debug`: verbose plus truncated payload and prompt excerpts
- GUI: `Advanced Runtime`
- CLI: `--verbosity`

`max_workers`

- Parallel worker count used for discovery, PDF/network enrichment, relevant-PDF downloads, screening preparation, and screening orchestration.
- GUI: `Advanced Runtime`
- CLI: `--max-workers`

`discovery_workers`, `io_workers`, `screening_workers`

- Optional per-stage worker overrides.
- `0` means "inherit `max_workers`".
- `discovery_workers` tunes source-query concurrency.
- `io_workers` tunes PDF enrichment, PDF download, and full-text preparation concurrency.
- `screening_workers` tunes AI-screening concurrency unless a local Hugging Face path forces serial execution.
- GUI: `Advanced Runtime`
- CLI:
  - `--discovery-workers`
  - `--io-workers`
  - `--screening-workers`

`request_timeout_seconds`

- HTTP timeout for external calls.
- GUI: `Advanced Runtime`
- CLI: `--request-timeout-seconds`

`partial_rerun_mode`

- Controls whether the pipeline should rerun everything or only the affected downstream stages.
- Choices:
  - `off`: full run
  - `reporting_only`: rebuild reports from stored paper state without redoing discovery or screening
  - `screening_and_reporting`: rerun screening on stored records, then regenerate reports
  - `pdfs_screening_reporting`: refresh PDF enrichment first, then rerun screening and reports
- Example:
  If you changed only report settings or export toggles, `reporting_only` is often enough.
- GUI: `Advanced Runtime`
- CLI: `--partial-rerun-mode`

`incremental_report_regeneration`

- Skips rewriting report artifacts whose content did not change.
- `Yes` means unchanged CSV, JSON, Markdown, and SQLite outputs are left untouched.
- `No` means report outputs are regenerated every run.
- Example:
  Turn this on when you want stable output timestamps during repeated reruns.
- GUI: `Advanced Runtime`
- CLI: `--incremental-report-regeneration` / `--no-incremental-report-regeneration`

`enable_async_network_stages`

- Enables the optional async orchestration layer for network-heavy stages such as multi-source discovery and network-bound paper mapping.
- `Yes` means eligible stages can run through the async path while preserving the final record order.
- `No` keeps the standard threaded executor path.
- GUI: `Advanced Runtime`
- CLI: `--enable-async-network-stages` / `--no-enable-async-network-stages`

`pdf_batch_size`

- Controls how many papers are processed together in one PDF acquisition batch.
- Smaller values reduce burst load and make progress easier to inspect.
- Larger values can improve throughput when remote PDF endpoints are stable.
- Example:
  `10` means the enrichment queue works in batches of ten papers at a time.
- GUI: `Advanced Runtime`
- CLI: `--pdf-batch-size`

`resume_mode`

- Reuse screening cache and skip repeated work for the same context.
- GUI: `Advanced Runtime`
- CLI: `--resume-mode`

`reset_query_records`

- Delete previously stored paper rows for the active query before the run starts.
- Useful when you want to rebuild the discovery set from scratch instead of merging into prior records.
- GUI: `Advanced Runtime`
- CLI: `--reset-query-records`

`clear_screening_cache`

- Delete cached screening decisions for the active screening context before the run starts.
- Useful when criteria, thresholds, prompts, or model choices changed and you want fresh scoring.
- GUI: `Advanced Runtime`
- CLI: `--clear-screening-cache`

`disable_progress_bars`

- Useful for CI or very clean logs.
- GUI: `Advanced Runtime`
- CLI: `--disable-progress-bars`

Deduplication and request safety:

- `title_similarity_threshold` -> `--title-similarity-threshold`

Verbose/debug logging switches:

- `log_http_requests` -> `--log-http-requests`
- `log_http_payloads` -> `--log-http-payloads`
- `log_llm_prompts` -> `--log-llm-prompts`
- `log_llm_responses` -> `--log-llm-responses`
- `log_screening_decisions` -> `--log-screening-decisions`

These toggles are especially useful when diagnosing:

- rate limits
- prompt formatting issues
- model-response parsing issues
- why a paper was kept or rejected

Per-source request throttling:

- `openalex_calls_per_second` -> `--openalex-calls-per-second`
- `semantic_scholar_calls_per_second` -> `--semantic-scholar-calls-per-second`
- `crossref_calls_per_second` -> `--crossref-calls-per-second`
- `springer_calls_per_second` -> `--springer-calls-per-second`
- `arxiv_calls_per_second` -> `--arxiv-calls-per-second`
- `pubmed_calls_per_second` -> `--pubmed-calls-per-second`
- `europe_pmc_calls_per_second` -> `--europe-pmc-calls-per-second`
- `core_calls_per_second` -> `--core-calls-per-second`
- `unpaywall_calls_per_second` -> `--unpaywall-calls-per-second`

These live in the GUI on the `Discovery` page and let you slow only the provider that is rate-limiting instead of slowing the entire run.

## Outputs

Depending on the active switches, the run can write:

- `papers.csv`
- `included_papers.csv`
- `excluded_papers.csv`
- `top_papers.json`
- `citation_graph.json`
- `prisma_flow.json`
- `review_summary.md`
- `included_papers.db`
- `excluded_papers.db`
- `run_config.json`

Typical main database content:

- title
- authors
- abstract
- year
- venue
- DOI
- source
- citation count
- reference count
- PDF link
- open-access flag
- relevance score
- relevance explanation
- inclusion decision
- references
- citations

Decision exports also preserve rationale such as:

- keep or exclude decision
- retain reason
- exclusion reason
- extracted passage
- matched inclusion criteria
- matched exclusion criteria
- matched banned topics

## Troubleshooting

Semantic Scholar `429`:

- public quota is rate-limited
- reduce `pages_to_retrieve` or `results_per_page`
- provide `semantic_scholar_api_key`
- rely more on OpenAlex, Crossref, arXiv, or Springer for that run

Springer finds nothing:

- check `springer_enabled`
- check `springer_api_key`

No PDFs downloaded:

- check `download_pdfs`
- check `pdf_download_mode`
- confirm open-access links exist
- confirm the target folders are writable

Local Hugging Face issues:

- install `requirements-local-llm.txt`
- check device and dtype values
- start with a smaller model if hardware is tight

GUI stop feels delayed:

- that is expected during an active HTTP request or model call
- the stop is controlled, not an immediate kill

## Testing And Quality

Current verified baseline:

- `220` tests passing
- `99.18%` app-code coverage excluding `tests/*`
- `99.18%` full-repository coverage including `tests/*`
- `ruff` clean
- `mypy` clean for the configured backend/tooling scope
- `compileall` clean
- `benchmark_report.py --fail-on-regression` clean

Commands:

```powershell
py -3 -m ruff check .
py -3 -m unittest discover -s tests -v
py -3 -m compileall .
py -3 -m coverage run -m unittest discover -s tests -v
py -3 -m coverage report -m --precision=2 --omit "tests/*"
py -3 -m coverage html -d results\coverage_html_app --omit "tests/*"
```

Detailed coverage bundle:

```powershell
py -3 coverage_report.py
```

This helper reruns the test suite under coverage and writes a JaCoCo-style bundle with:

- console summary
- low-coverage file list
- missing line ranges per file
- an isolated coverage data file inside the chosen results directory, so separate report runs do not collide
- HTML report
- JSON summary
- Markdown report

Useful options:

- `--results-dir results\coverage_report`
- `--top-files 25`
- `--fail-under 99`
- `--include-tests`

## Benchmark Report Helper

Use the benchmark helper when you want a lightweight regression signal for local performance-sensitive paths.

```powershell
py -3 benchmark_report.py
```

Fail the command if any benchmark exceeds its configured threshold:

```powershell
py -3 benchmark_report.py --fail-on-regression
```

Artifacts:

- `results/benchmark_report/benchmark_report.txt`
- `results/benchmark_report/benchmark_report.md`
- `results/benchmark_report/benchmark_summary.json`
- `results/benchmark_report/benchmark_results.csv`

Default thresholds live in:

- [benchmark_baselines.json](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/configs/benchmark_baselines.json)

## Type-Checking And CI

Unified tool configuration now lives in:

- [pyproject.toml](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/pyproject.toml)

Run backend and tooling type-checks with:

```powershell
py -3 -m mypy
```

The CI workflow lives in:

- [quality.yml](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/.github/workflows/quality.yml)

It runs:

- Ruff linting
- MyPy type-checking
- provider-contract tests
- the full unit suite
- coverage gates
- benchmark regression smoke checks

## Provider-Contract Tests

Provider-contract tests keep discovery adapters aligned to the same normalized `PaperMetadata` contract.

Run them directly with:

```powershell
py -3 -m unittest tests.test_provider_contracts -v
```

They verify that providers return, at minimum:

- a non-empty title
- the expected source label
- the active `query_key`
- list-based `authors`
- dictionary-based `raw_payload`
- dictionary-based `external_ids`

## Code Map

Main files and directories:

- `main.py`: launcher and application entry
- `config.py`: validated runtime config and CLI parser
- `database.py`: SQLite persistence and screening cache
- `pipeline/pipeline_controller.py`: orchestration
- `analysis/`: screening logic and provider clients
- `discovery/`: source clients and import adapters
- `acquisition/`: PDF fetch and full-text extraction
- `reporting/`: CSV/JSON/Markdown/SQLite outputs
- `ui/`: desktop GUI, launcher, and view model
- `tests/`: unit and integration coverage

## Recommended Usage Pattern

1. Start with the GUI for initial setup.
2. Save a profile once the settings look right.
3. Run a smaller discovery first with `verbose`.
4. Tune source mix, thresholds, and pass chain.
5. Move to a config-file-based run for reproducible execution.
6. Archive the `run_config.json` together with the result files.
