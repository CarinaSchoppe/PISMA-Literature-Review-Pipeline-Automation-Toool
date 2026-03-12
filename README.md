# PRISMA Literature Review Pipeline

API-first, production-oriented Python project for systematic literature discovery, deduplication, citation expansion, AI-assisted screening, PDF acquisition, and report generation.

The project supports two equal entry modes:

* a guided desktop UI for local interactive use
* a scriptable CLI for repeatable and automated runs

No Jupyter notebook is required.

For full operating instructions, see [HANDBOOK.md](HANDBOOK.md).
For configuration details, see [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md).
For CLI usage patterns, see [CLI_REFERENCE.md](CLI_REFERENCE.md).
For GUI workflow notes, see [GUI_GUIDE.md](GUI_GUIDE.md).
For the planned target state and roadmap, see [ROADMAP.md](ROADMAP.md).

---

## Overview

This pipeline is built for structured literature-review workflows where reproducibility, screening transparency, and multi-source metadata collection matter.

It can:

* collect metadata from supported scholarly APIs
* merge and deduplicate records by DOI and title similarity
* persist papers, screening cache, and run state in SQLite
* expand results through backward and forward citation snowballing
* enrich records with open-access PDF metadata and optionally download PDFs
* screen papers with heuristics or one or more LLM passes
* extract paper keyphrases locally and compare them against weighted research keywords
* export accepted and rejected records with reasons
* generate PRISMA-style flow outputs and ranked results

Workflow:

```text
input -> discovery -> deduplication -> database storage -> citation expansion -> pdf enrichment -> AI screening -> scoring -> ranking -> report generation
```

## Documentation Map

Use the docs in this order:

* [README.md](README.md)
  Short project overview and quick-start guide.
* [HANDBOOK.md](HANDBOOK.md)
  Operator guide with workflow explanations and runtime behavior notes.
* [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md)
  Detailed setting-by-setting configuration reference.
* [CLI_REFERENCE.md](CLI_REFERENCE.md)
  Command-line patterns, examples, and flag usage notes.
* [GUI_GUIDE.md](GUI_GUIDE.md)
  Guided desktop workbench layout, scrolling, and interaction model.
* [ROADMAP.md](ROADMAP.md)
  Planned future direction.

---

## Key Capabilities

* guided desktop UI and classic console wizard
* headless CLI and JSON config-file runs
* SQLite persistence for run state and screening cache
* DOI and title-similarity deduplication
* backward and forward citation snowballing
* separate `collect` and `analyze` run modes
* configurable PDF download strategies
* optional full-text extraction from downloaded PDFs
* included and excluded outputs with rationale
* PRISMA-style flow artifacts
* deterministic offline fixture mode for testing
* multi-threaded discovery, enrichment, and screening orchestration
* per-source throttling and stage-specific worker overrides
* smarter `429` backoff with `Retry-After` support and bounded exponential fallback
* persistent on-disk source-response cache for repeatable GET requests
* incremental report regeneration that skips unchanged artifacts
* partial rerun modes for downstream-only execution
* batch-based PDF acquisition queueing
* optional async orchestration for network-heavy stages
* provider-contract tests for normalized discovery adapters
* benchmark fixtures and local performance regression reports
* `pyproject.toml`-based tooling unification
* GitHub Actions quality gates for lint, type-checking, tests, coverage, and benchmark smoke runs
* profile save/load in the GUI

---

## Supported Discovery Sources

### Live API sources

* OpenAlex
* Semantic Scholar
* Crossref
* Springer Nature Metadata API
* arXiv API
* PubMed
* Europe PMC
* CORE

### Live HTML sources

* Google Scholar result pages with configurable page-depth traversal and bounded throttling

### Manual import sources

* Google Scholar export files
* ResearchGate export files
* arbitrary CSV or JSON metadata imports
* offline fixture files for deterministic testing

### Boundary

The project is still API-first. Official scholarly APIs remain the preferred path. Google Scholar is available as a bounded HTML discovery source with explicit page-depth controls, while ResearchGate remains import-based. This keeps discovery broad without turning the main architecture into an unrestricted browser crawler.

---

## Supported Screening Providers

Built-in screening modes:

* `heuristic`
* `openai_compatible`
* `gemini`
* `ollama`
* `huggingface_local`

This supports:

* OpenAI-compatible endpoints
* Google Gemini
* Ollama-hosted local models
* local Hugging Face models, including open-weight models such as `Qwen/Qwen3-14B` and `openai/gpt-oss-20b`

### Local semantic topic prefilter

The pipeline can also run a local CPU-friendly semantic relevance prefilter before deeper screening.

Default local embedding model:

* `sentence-transformers/all-MiniLM-L6-v2`

The prefilter:

* builds one review brief from the topic, research question, objective, keywords, and inclusion criteria
* uses the research topic, research question, and review objective directly in the local research-fit explanation path
* extracts paper keyphrases from title, abstract, and metadata keywords
* compares extracted topics against weighted research keywords, per-keyword thresholds, and minimum-match requirements
* embeds the review brief and each paper locally on the machine
* compares them with cosine similarity
* classifies each paper as `HIGH_RELEVANCE`, `REVIEW`, or `LOW_RELEVANCE`
* produces a research-fit badge of `STRONG_FIT`, `NEAR_FIT`, or `WEAK_FIT`
* can automatically filter `LOW_RELEVANCE` papers before more expensive screening
* caches the loaded embedding model in-process so repeated paper scoring does not reload the model
* keeps the default text window and character limits moderate for normal CPU-only desktop hardware

This path is designed for CPU-only execution on normal desktop hardware and remains usable offline after the initial model download.

Weighted research-fit rules can be written as plain phrases or `keyword|weight|threshold`, for example:

* `systematic review|1.8|70`
* `large language models|1.4|60`
* `screening automation`

When the explicit threshold is omitted, the rule falls back to the global strong-fit threshold.

Multi-pass screening is supported. Each pass can define:

* provider
* threshold
* decision mode
* maybe margin
* model override
* minimum previous-pass score required before execution

---

## Desktop UI

Launching without explicit mode flags opens the launcher:

```powershell
py -3 main.py
```

The guided workbench includes:

- startup launcher with guided UI or classic console wizard
- a refreshed light theme with higher-contrast tabs, accent actions, danger-stop styling, and cleaner tables
- English-only visible text across the GUI, CLI prompts, handbook entries, hover help, and status guidance
- settings pages:
    - `Review Setup`
    - `Discovery`
    - `AI Screening`
    - `Connections and Keys`
    - `Storage and Output`
    - `Advanced Runtime`
- a left-hand page rail so the settings follow the review workflow instead of one long stacked panel
- a resizable three-pane settings shell, so you can widen the editor or the inspector instead of being stuck with one fixed layout
- a right-hand inspector with dedicated `Find`, `Quick Edit`, `Guides`, and `Summary` tabs
- compact and advanced settings modes so you can collapse or reveal explanatory section text depending on how dense you want the workspace to be
- collapsible workspace and settings overview blocks so the real editing area stays usable without fullscreen
- responsive compact-window behavior that automatically trims oversized overview sections and tightens pane defaults on smaller windows
- scrollable settings pages, a scrollable quick-edit panel, and a scrollable summary inspector so the window stays usable on smaller screens
- scrollable logs, result tables, handbook content, artifact browser tables, chart previews, run history, and screening audit views so no important content is trapped off-screen on smaller windows
- mouse-wheel routing follows the active inner widget so smaller windows stay usable without fullscreen
- `Shift + MouseWheel` scrolls wide tables and previews horizontally where available
- `Show advanced settings` toggle so lower-level runtime options stay out of the way until needed
- persisted GUI defaults for `Compact` vs `Advanced` density and whether advanced pages start expanded
- quick-edit controls for the most-used model, threshold, and output settings, without forcing every option onto the main form at once
- a richer visual pass-chain builder with provider-specific model suggestions, per-pass previews, duplication, ordering, and entry-score gates
- stronger grouped path configuration for database paths, result folders, and paper PDF folders
- provider health indicators so you can see which sources or AI backends are ready, disabled, or missing credentials before a run
- searchable `Handbook` tab
- hover help and keyboard-focus help for settings, with detailed English explanations that describe the purpose of each flag, what changes when a switch is on or off, and concrete examples for common workflows
- placeholder text and nearby input guidance for review-topic, keyword, criteria, and filter fields, including explicit separator examples for commas, semicolons, and line breaks
- live `Run Log` tab
- semantic log highlighting with badges for neutral info, green success, orange warnings, red errors, and dimmed trace lines
- visible status badges across the workbench, including outputs, run history, screening audit, provider health, and the embedded document viewer
- result tabs for:
  - `All Papers`
  - `Included`
  - `Excluded`
  - `Research Fit`
  - `Outputs`
  - `Charts`
  - `Run History`
  - `Screening Audit`
  - `Document Viewer`
- double-click result and audit rows to open the embedded document viewer
- document previews combine local PDF excerpts when available with screening rationale, retain/exclude reasoning, and research-fit context
- the `Research Fit` tab shows extracted topics, per-keyword match percentages, per-keyword thresholds, threshold deltas, matched-rule counts, and strong/near/weak fit badges
- the weighted-keyword field in `AI Screening` now uses a visual keyword-rule builder so you can add, remove, duplicate, and tune rule rows without editing raw text
- the embedded document viewer can render local PDF pages directly inside the tab when `Pillow` and `pypdfium2` are available
- the document viewer includes page navigation, zoom controls, source/decision/file badges, and falls back to text preview when no renderable local PDF exists
- export preview before the run starts, so you can confirm which files and folders the current settings will produce
- an artifact browser with summary panes and open-folder actions for generated files
- `Analyze Stored Results` button to skip discovery and rerun screening/reporting
- `Force Stop` button for controlled stop requests
- path pickers for database, results, PDF, cache, and import paths
- error pop-ups for invalid configuration, failed runs, stopped runs, and invalid paths

The GUI is not a separate implementation. It edits the same validated runtime configuration used by the CLI.

The settings shell is also hardened against stale Tk `after(...)` callbacks. Responsive pane updates and settings-page sync are debounced so smaller-window resizing and page changes do not produce noisy popup callback failures.

For the current page-by-page workbench behavior, including compact-window usage, see [GUI_GUIDE.md](GUI_GUIDE.md).

---

## CLI And GUI Parity

Runtime settings can be configured through:

* CLI flags
* JSON config files
* guided GUI forms

That includes:

* discovery source toggles
* discovery breadth and result limits
* provider and model selection
* pass-chain setup
* API keys and endpoint URLs
* PDF download behaviour
* export options
* database and output paths
* worker/thread controls
* HTTP cache and retry controls
* partial rerun and incremental regeneration controls
* async network-stage toggles and PDF batch sizing
* rerun and cache-reset controls
* logging and verbosity settings

---

## Runtime Resilience And Incremental Workflows

The runtime now includes explicit controls for repeated review work, rate-limit handling, and downstream-only reruns.

### Smarter `429` backoff

The HTTP layer now:

* respects `Retry-After` when a provider returns `429 Too Many Requests`
* falls back to bounded exponential backoff when `Retry-After` is missing
* keeps transport retries for `5xx` failures separate from rate-limit retries
* proactively slows down Semantic Scholar requests with a rolling requests-per-minute window and an optional extra delay between calls
* logs proactive throttle sleeps, 429 backoff waits, and exhausted retry paths so rate-limit behavior is visible in both CLI and GUI logs

Relevant settings:

* `--http-retry-max-attempts`
* `--http-retry-base-delay-seconds`
* `--http-retry-max-delay-seconds`
* `--semantic-scholar-max-requests-per-minute`
* `--semantic-scholar-request-delay-seconds`
* `--semantic-scholar-retry-attempts`
* `--semantic-scholar-retry-backoff-strategy`
* `--semantic-scholar-retry-backoff-base-seconds`

Semantic Scholar guidance:

* lower `semantic_scholar_max_requests_per_minute` if the public quota is unstable
* increase `semantic_scholar_request_delay_seconds` when you want a safety gap between requests even before a `429`
* keep `semantic_scholar_retry_backoff_strategy=exponential` unless you have a strong reason to prefer `fixed` or `linear`
* if retries are exhausted, the affected Semantic Scholar page is skipped cleanly and the rest of the run continues where possible

### Local MiniLM topic prefilter

The local topic prefilter is a lightweight semantic relevance gate that runs before or alongside deeper screening.

Important settings:

* `--topic-prefilter-enabled`
* `--topic-prefilter-filter-low-relevance`
* `--topic-prefilter-high-threshold`
* `--topic-prefilter-review-threshold`
* `--topic-prefilter-text-mode`
* `--topic-prefilter-max-chars`
* `--topic-prefilter-model`

Practical defaults:

* `HIGH_RELEVANCE` when similarity is at least `0.75`
* `REVIEW` when similarity is between `0.55` and `0.75`
* `LOW_RELEVANCE` below `0.55`

The generated explanation includes the similarity score, thresholds used, selected paper sections, keyword overlap, and the resulting classification.

### Google Scholar page depth

Google Scholar discovery can now be bounded explicitly instead of relying only on the general source limit.

Important settings:

* `--google-scholar-enabled`
* `--google-scholar-pages`
* `--google-scholar-page-min`
* `--google-scholar-page-max`
* `--google-scholar-results-per-page`
* `--google-scholar-calls-per-second`

Behavior:

* each configured page is fetched in order
* the GUI exposes both a slider and a numeric control for page depth so you can tune breadth precisely
* the run stops early if the configured per-source limit is reached
* retrieval volume is roughly `page_count x configured results_per_page x number_of_generated_queries`, subject to deduplication and stop conditions
* partial page failures are logged and skipped instead of crashing the whole run
* a force-stop request is checked between query and page boundaries so long Scholar traversals can stop cleanly
* metadata is deduplicated afterward through the normal DOI and title-based pipeline

Large page counts can increase run time and raise the chance of rate-limits or HTML-structure drift, so the default path remains intentionally conservative.

### Persistent source-response cache

Eligible GET requests can be cached on disk and reused across runs.

Useful when:

* you are re-running the same discovery query while tuning thresholds
* a provider is rate-limited and you want to avoid fetching identical pages again
* you want faster local iteration on screening or reporting settings

Relevant settings:

* `--http-cache-enabled` / `--no-http-cache-enabled`
* `--http-cache-dir`
* `--http-cache-ttl-seconds`

### Partial rerun modes

You can rerun only the affected downstream stages instead of restarting the full pipeline each time.

Available modes:

* `off`
* `reporting_only`
* `screening_and_reporting`
* `pdfs_screening_reporting`

Relevant setting:

* `--partial-rerun-mode`

### Incremental report regeneration

When enabled, report generation skips rewriting artifacts whose content did not change.

Relevant setting:

* `--incremental-report-regeneration` / `--no-incremental-report-regeneration`

### Batch PDF acquisition queue

PDF enrichment and relevant-only PDF downloads now run in configurable batches.

Relevant setting:

* `--pdf-batch-size`

### Optional async orchestration

Eligible network-heavy stages can use the async orchestration path while preserving deterministic final ordering.

Relevant setting:

* `--enable-async-network-stages` / `--no-enable-async-network-stages`

---

## Quality Tooling

The engineering toolchain is now unified around:

* [pyproject.toml](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/pyproject.toml) for packaging metadata plus Pytest, pytest-cov, Ruff, Coverage, and MyPy configuration
* [quality.yml](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/.github/workflows/quality.yml) for CI quality gates
* [coverage_report.py](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/coverage_report.py) for JaCoCo-style coverage bundles
* [benchmark_report.py](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/benchmark_report.py) for local benchmark regression reports
* [test_provider_contracts.py](/C:/Users/Carina/.codex/worktrees/067c/PRISMA-Literature-Review/tests/test_provider_contracts.py) for provider contract coverage

Recommended local quality commands:

```powershell
py -3 -m ruff check .
py -3 -m mypy
py -3 -m pytest -v
py -3 coverage_report.py --results-dir results\coverage_report --top-files 25 --fail-under 99.5
py -3 benchmark_report.py --fail-on-regression
```

### Optional async network orchestration

Discovery and other network-heavy mapping stages can run through an async orchestration path while preserving stable output ordering.

Relevant setting:

* `--enable-async-network-stages` / `--no-enable-async-network-stages`

---

## Project Structure

```text
project_root/
|-- main.py
|-- config.py
|-- database.py
|-- requirements.txt
|-- requirements-local-llm.txt
|-- README.md
|-- acquisition/
|   |-- full_text_extractor.py
|   `-- pdf_fetcher.py
|-- analysis/
|   |-- ai_screener.py
|   |-- llm_clients.py
|   `-- relevance_scoring.py
|-- citation/
|   `-- citation_expander.py
|-- discovery/
|   |-- arxiv_client.py
|   |-- core_client.py
|   |-- crossref_client.py
|   |-- europe_pmc_client.py
|   |-- fixture_client.py
|   |-- manual_import_client.py
|   |-- null_citation_provider.py
|   |-- openalex_client.py
|   |-- protocols.py
|   |-- pubmed_client.py
|   |-- semantic_scholar_client.py
|   `-- springer_client.py
|-- models/
|   `-- paper.py
|-- pipeline/
|   `-- pipeline_controller.py
|-- reporting/
|   `-- report_generator.py
|-- ui/
|   |-- desktop_app.py
|   |-- launcher.py
|   `-- view_model.py
|-- utils/
|   |-- deduplication.py
|   |-- http.py
|   `-- text_processing.py
`-- tests/
    |-- fixtures/
    `-- ...
```

---

## Installation

Windows PowerShell example:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
```

Optional local-model runtime:

```powershell
py -3 -m pip install -r requirements-local-llm.txt
```

You can also install directly from the unified project metadata:

```powershell
py -3 -m pip install -e .[dev]
```

For local transformer support:

```powershell
py -3 -m pip install -e .[dev,local-llm]
```

---

## Environment Variables

Recommended environment variables:

* `UNPAYWALL_EMAIL`
* `CROSSREF_MAILTO`
* `SEMANTIC_SCHOLAR_API_KEY`
* `SPRINGER_API_KEY`
* `CORE_API_KEY`
* `OPENAI_API_KEY`
* `OPENAI_BASE_URL`
* `OPENAI_MODEL`
* `GEMINI_API_KEY` or `GOOGLE_API_KEY`
* `GEMINI_BASE_URL`
* `GEMINI_MODEL`
* `OLLAMA_BASE_URL`
* `OLLAMA_MODEL`
* `OLLAMA_API_KEY`
* `HF_MODEL_ID`
* `HF_TASK`
* `HF_DEVICE`
* `HF_DTYPE`
* `HF_MAX_NEW_TOKENS`
* `HF_HOME` or `TRANSFORMERS_CACHE`
* `HF_TRUST_REMOTE_CODE`
* `LLM_TEMPERATURE`
* `EUROPE_PMC_CALLS_PER_SECOND`
* `CORE_CALLS_PER_SECOND`

If no remote or local LLM backend is configured, the project still works with the heuristic screener.

---

## Quick Start

### Guided launcher

```powershell
py -3 main.py
```

### Open the desktop UI directly

```powershell
py -3 main.py --ui
```

### Open the console wizard directly

```powershell
py -3 main.py --wizard
```

### Run headless

```powershell
py -3 main.py ^
  --topic "AI-assisted systematic literature reviews" ^
  --keywords "large language models,systematic review,screening" ^
  --pages 2 ^
  --year-start 2020 ^
  --year-end 2026 ^
  --max-papers 40 ^
  --run-mode analyze ^
  --verbosity verbose ^
  --citation-snowballing ^
  --download-pdfs ^
  --pdf-download-mode relevant_only ^
  --relevant-pdfs-dir papers\relevant_keep
```

### Run from config file

```powershell
py -3 main.py --config-file tests\fixtures\offline_config.json
```

### Analyze stored results without new discovery

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --skip-discovery ^
  --run-mode analyze
```

---

## Example Provider Runs

### OpenAI-compatible

```powershell
py -3 main.py ^
  --topic "LLM evaluation studies" ^
  --keywords "llm,evaluation,benchmark" ^
  --llm-provider openai_compatible ^
  --openai-model gpt-5.4 ^
  --verbosity verbose
```

### Gemini

```powershell
py -3 main.py ^
  --topic "LLM evaluation studies" ^
  --keywords "llm,evaluation,benchmark" ^
  --llm-provider gemini ^
  --gemini-model gemini-2.5-flash ^
  --verbosity verbose
```

### Ollama

```powershell
py -3 main.py ^
  --config-file configs\ollama_local.example.json
```

### Local Hugging Face

```powershell
py -3 main.py ^
  --llm-provider huggingface_local ^
  --huggingface-model Qwen/Qwen3-14B
```

---

## Multi-Pass Analysis

Example pass chain from the CLI:

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --analysis-pass "fast|huggingface_local|65|strict|8|Qwen/Qwen3-14B|0" ^
  --analysis-pass "deep|gemini|82|triage|10|gemini-2.5-flash|65" ^
  --analysis-pass "final|openai_compatible|88|strict|5|gpt-5.4|82"
```

The same pass-chain logic can be edited in the GUI through `Edit Pass Chain`.

---

## Output Artifacts

Depending on configuration, the project can write:

* `results/papers.csv`
* `results/included_papers.csv`
* `results/excluded_papers.csv`
* `results/top_papers.json`
* `results/citation_graph.json`
* `results/review_summary.md`
* `results/prisma_flow.json`
* `results/prisma_flow.md`
* `results/included_papers.db`
* `results/excluded_papers.db`
* `results/run_config.json`
* PDFs under `papers/` or the configured relevant-PDF directory

The main SQLite database stores:

* bibliographic metadata
* source information
* abstract and enrichment data
* references and citations
* screening decisions
* screening explanations
* cached screening context for resume and re-analysis control

---

## Important Runtime Controls

### Discovery

* source toggles for OpenAlex, Semantic Scholar, Crossref, Springer, arXiv, PubMed, Europe PMC, CORE, and Google Scholar
* per-source rate limits
* dedicated Google Scholar page-depth controls
* `pages_to_retrieve`
* `results_per_page`
* `max_discovered_records`
* `min_discovered_records`
* `max_papers_to_analyze`
* `skip_discovery`
* `citation_snowballing_enabled`
* `discovery_strategy`

### Screening

* `llm_provider`
* pass-chain definitions
* `relevance_threshold`
* `decision_mode`
* `maybe_threshold_margin`
* `analyze_full_text`
* `full_text_max_chars`

### Storage and output

* `download_pdfs`
* `pdf_download_mode`
* `output_csv`
* `output_json`
* `output_markdown`
* `output_sqlite_exports`
* `data_dir`
* `papers_dir`
* `relevant_pdfs_dir`
* `results_dir`
* `database_path`

### Runtime and logging

* `run_mode`
* `verbosity`
* `max_workers`
* `discovery_workers`
* `io_workers`
* `screening_workers`
* `request_timeout_seconds`
* `resume_mode`
* `reset_query_records`
* `clear_screening_cache`
* `disable_progress_bars`
* `log_http_requests`
* `log_http_payloads`
* `log_llm_prompts`
* `log_llm_responses`
* `log_screening_decisions`

`max_workers` controls the global thread-pool fallback. `discovery_workers`, `io_workers`, and `screening_workers` can override that value per stage. A value of `0` means “inherit the global value”.

---

## Error Handling And Stop Behaviour

The GUI surfaces operational issues through:

* validation pop-ups for invalid configuration
* path pop-ups for missing or invalid output/file targets
* failure pop-ups when a worker raises an exception
* stop warnings when a run ends due to a user stop request

`Force Stop` is a controlled stop request, not a hard kill. A running HTTP request or model call may need a moment to complete before shutdown finishes.

---

## Testing And Quality

Latest local verification for this repository state is written to generated artifacts under:

* `results/coverage_report/`
* `results/coverage_report_all/`

The enforced release gate is:

* production-code coverage `>= 99.5%`
* clean `ruff` lint
* clean `mypy` type-checking for the configured backend and tooling scope
* clean `compileall`
* clean benchmark regression pass with `benchmark_report.py --fail-on-regression`

Run the test suite:

```powershell
py -3 -m pytest -v
```

Run lint:

```powershell
py -3 -m ruff check .
```

Run compile validation:

```powershell
py -3 -m compileall .
```

Measure app-code coverage with `pytest-cov`:

```powershell
py -3 -m pytest -v --cov=. --cov-config=pyproject.toml --cov-report=term-missing --cov-report=html:results\coverage_html_app --cov-report=json:results\coverage_html_app\coverage.json tests
```

Generate a JaCoCo-style coverage bundle with `pytest` and `pytest-cov`:

```powershell
py -3 coverage_report.py
```

Coverage scope note:

* the default project coverage configuration omits `tests/*`
* a plain `python -m coverage report` therefore describes production-code coverage unless the run was generated with `--include-tests`
* use `coverage_report.py --include-tests ...` only when you explicitly want a whole-tree reference report that includes test modules too

Generate the production-code release gate:

```powershell
py -3 coverage_report.py --results-dir results\coverage_report --top-files 25 --fail-under 99.5
```

Generate an optional whole-tree reference report, including tests:

```powershell
py -3 coverage_report.py --include-tests --results-dir results\coverage_report_all --top-files 25
```

Offline deterministic smoke test:

```powershell
py -3 main.py --config-file tests\fixtures\offline_config.json
```

Generated reports include:

* `results/coverage_report/coverage_report.txt`
* `results/coverage_report/coverage_report.md`
* `results/coverage_report/coverage_summary.json`
* `results/coverage_report/junit.xml`
* `results/coverage_report/pytest_terminal.txt`
* `results/coverage_report/html/index.html`
* `results/coverage_html_app/index.html`

Optional whole-tree reference reports can be written under `results/coverage_report_all/`.

Each coverage-report run uses its own coverage data file inside the target results directory, so separate report runs do not collide with the root `.coverage` file.

Run the benchmark regression helper:

```powershell
py -3 benchmark_report.py
```

Fail the run when a benchmark baseline is exceeded:

```powershell
py -3 benchmark_report.py --fail-on-regression
```

Generated benchmark artifacts include:

* `results/benchmark_report/benchmark_report.txt`
* `results/benchmark_report/benchmark_report.md`
* `results/benchmark_report/benchmark_summary.json`
* `results/benchmark_report/benchmark_results.csv`

The default thresholds live in `configs/benchmark_baselines.json`.

---

## Known Boundaries

* Semantic Scholar may return `429` rate-limit responses on public quotas
* Google Scholar is available through bounded HTML result traversal, while ResearchGate remains import-based
* Springer live discovery requires a valid API key
* local Hugging Face inference depends on installed runtime and available hardware
* full-text extraction depends on PDF availability and optional `pypdf`

---

## Recommended Workflow

### For interactive use

1. Start with the guided UI.
2. Enter topic, research question, objective, and include/exclude criteria.
3. Choose discovery sources and search breadth.
4. Select a screening provider or multi-pass chain.
5. Decide between metadata-only collection and full analysis.
6. Choose output, database, and PDF locations.
7. Run with `verbose` first while tuning settings.
8. Save the setup as a profile.

### For repeatable runs

1. Save a JSON config or GUI profile.
2. Run headless from the CLI.
3. Archive the generated outputs together with the run config snapshot.

---

## Documentation

* [HANDBOOK.md](HANDBOOK.md) — full operator reference
* [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) — detailed setting reference
* [CLI_REFERENCE.md](CLI_REFERENCE.md) — command-line usage reference
* [GUI_GUIDE.md](GUI_GUIDE.md) — guided desktop workbench notes
* [ROADMAP.md](ROADMAP.md) — planned feature roadmap





