# PRISMA Literature Review Pipeline

API-first, production-oriented Python project for systematic literature discovery, deduplication, citation expansion, AI-assisted screening, PDF acquisition, and report generation.

The project is designed around two equally supported entry modes:

- guided desktop UI with tabs, handbook help, hover explanations, live logs, result tables, and a force-stop button
- scriptable CLI with config-file support for repeatable and automated runs

No Jupyter notebook is required. The intended workflow is local desktop UI or CLI.

For the full operator reference, see [HANDBOOK.md](HANDBOOK.md). For the planned target state and feature roadmap, see [ROADMAP.md](ROADMAP.md).

## What The Project Does

The pipeline can:

- collect metadata from supported scholarly APIs
- merge and deduplicate records by DOI and title similarity
- persist papers, screening cache, and run state in SQLite
- expand records through backward and forward citation snowballing
- enrich records with open-access PDF metadata and optionally download PDFs
- screen papers with heuristic rules or one or more LLM passes
- export accepted and rejected records with reasons into CSV, JSON, Markdown, and SQLite
- generate PRISMA-style flow artifacts and ranked outputs

The workflow order is:

```text
input -> discovery -> deduplication -> database storage -> citation expansion -> pdf enrichment -> AI screening -> scoring -> ranking -> report generation
```

## Current Quality Baseline

The repository is maintained with a tested baseline of:

- `156` passing tests
- `99.04%` app-code coverage excluding `tests/*`
- `99.09%` full-repository coverage including `tests/*`
- clean `ruff` lint
- clean `compileall`

You can reproduce that locally with the commands in the `Testing And Quality` section.

## Supported Discovery Sources

Live API sources:

- OpenAlex
- Semantic Scholar
- Crossref
- Springer Nature Metadata API
- arXiv API
- PubMed

Manual import sources:

- Google Scholar export files
- ResearchGate export files
- arbitrary CSV or JSON metadata imports
- offline fixture files for deterministic testing

Important boundary:

- the project is API-first
- Google Scholar and ResearchGate are handled through manual imports, not direct live scraping
- this keeps the workflow more stable and easier to test

## Supported Screening Providers

Built-in screening modes:

- `heuristic`
- `openai_compatible`
- `gemini`
- `ollama`
- `huggingface_local`

This means the project can use:

- ChatGPT/OpenAI-compatible endpoints
- Google Gemini
- Ollama-hosted local models
- local Hugging Face models, including open-weight models such as `Qwen/Qwen3-14B` and `openai/gpt-oss-20b`

Multi-pass screening is supported. Each pass can define:

- provider
- threshold
- decision mode
- maybe margin
- model override
- minimum previous-pass score required before the pass runs

## Guided Desktop UI

Start the project without explicit run flags to open the launcher:

```powershell
py -3 main.py
```

The guided desktop workbench provides:

- startup launcher with guided UI or classic console wizard
- settings pages:
  - `Review Setup`
  - `Discovery`
  - `AI Screening`
  - `Storage and Output`
  - `Runtime and Logs`
- quick-access controls for the most-used model and output settings
- searchable `Handbook` tab
- hover help and keyboard-focus help for settings
- live `Run Log` tab
- result tabs for:
  - `All Papers`
  - `Included`
  - `Excluded`
  - `Outputs`
- `Analyze Stored Results` button to skip discovery and rerun screening/reporting
- `Force Stop` button for controlled stop requests
- path pickers for database, results, PDF, cache, and import paths
- error pop-ups for invalid configuration, failed runs, stopped runs, and invalid paths

The GUI is not a second implementation. It edits the same validated runtime config used by the CLI.

## CLI And GUI Setting Parity

The project is structured so runtime settings are configurable in both places:

- CLI flags
- JSON config files
- guided GUI form

That includes:

- discovery source toggles
- discovery breadth and result limits
- min/max discovery gates
- thresholds and decision mode
- pass-chain setup
- provider and model selection
- API keys and endpoint URLs
- PDF download behavior
- CSV/JSON/Markdown/SQLite export switches
- path selection for state, outputs, PDFs, and database files
- logging and verbosity controls
- resume and progress-bar controls

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
|   |-- crossref_client.py
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

## Core Features

- interactive guided UI and classic console wizard
- headless CLI and JSON config-file runs
- SQLite persistence for runtime state and screening cache
- DOI and title-similarity deduplication
- backward and forward citation snowballing
- separate `collect` and `analyze` run modes
- configurable PDF download modes:
  - all open-access PDFs
  - only relevant PDFs after screening
- optional full-text extraction from downloaded PDFs
- included and excluded outputs with rationale
- PRISMA-style flow output
- structured verbose and debug logging
- profile save/load in the GUI
- deterministic offline fixture mode for testing
- multi-threaded discovery and screening orchestration

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

## Environment Variables

Recommended environment variables:

- `UNPAYWALL_EMAIL`
- `CROSSREF_MAILTO`
- `SEMANTIC_SCHOLAR_API_KEY`
- `SPRINGER_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`
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
- `HF_HOME` or `TRANSFORMERS_CACHE`
- `HF_TRUST_REMOTE_CODE`
- `LLM_TEMPERATURE`

If no remote or local LLM backend is configured, the project still works with the heuristic screener.

## Quick Start

Guided launcher:

```powershell
py -3 main.py
```

Open the desktop UI directly:

```powershell
py -3 main.py --ui
```

Classic console wizard directly:

```powershell
py -3 main.py --wizard
```

Headless run:

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
  --relevant-pdfs-dir papers\\relevant_keep
```

Config-file run:

```powershell
py -3 main.py --config-file tests\fixtures\offline_config.json
```

Analyze existing stored results without new discovery:

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --skip-discovery ^
  --run-mode analyze
```

## Example Provider Runs

OpenAI-compatible:

```powershell
py -3 main.py ^
  --topic "LLM evaluation studies" ^
  --keywords "llm,evaluation,benchmark" ^
  --llm-provider openai_compatible ^
  --openai-model gpt-5.4 ^
  --verbosity verbose
```

Gemini:

```powershell
py -3 main.py ^
  --topic "LLM evaluation studies" ^
  --keywords "llm,evaluation,benchmark" ^
  --llm-provider gemini ^
  --gemini-model gemini-2.5-flash ^
  --verbosity verbose
```

Ollama:

```powershell
py -3 main.py ^
  --config-file configs\ollama_local.example.json
```

Local Hugging Face:

```powershell
py -3 main.py ^
  --llm-provider huggingface_local ^
  --huggingface-model Qwen/Qwen3-14B
```

## Multi-Pass Analysis

Example pass chain from the CLI:

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --analysis-pass "fast|huggingface_local|65|strict|8|Qwen/Qwen3-14B|0" ^
  --analysis-pass "deep|gemini|82|triage|10|gemini-2.5-flash|65" ^
  --analysis-pass "final|openai_compatible|88|strict|5|gpt-5.4|82"
```

The same pass-chain logic is editable in the GUI through `Edit Pass Chain`.

## Output Artifacts

Depending on config, the project writes:

- `results/papers.csv`
- `results/included_papers.csv`
- `results/excluded_papers.csv`
- `results/top_papers.json`
- `results/citation_graph.json`
- `results/review_summary.md`
- `results/prisma_flow.json`
- `results/prisma_flow.md`
- `results/included_papers.db`
- `results/excluded_papers.db`
- `results/run_config.json`
- PDFs under `papers/` or the configured relevant-PDF directory

The main SQLite database stores:

- bibliographic metadata
- source information
- abstract and enrichment data
- references and citations
- screening decisions
- screening explanations
- cached screening context for resume and re-analysis control

## Important Runtime Controls

Discovery:

- source toggles for OpenAlex, Semantic Scholar, Crossref, Springer, arXiv, and PubMed
- `pages_to_retrieve`
- `results_per_page`
- `max_discovered_records`
- `min_discovered_records`
- `max_papers_to_analyze`
- `skip_discovery`
- `citation_snowballing_enabled`
- `discovery_strategy`

Screening:

- `llm_provider`
- pass-chain definitions
- `relevance_threshold`
- `decision_mode`
- `maybe_threshold_margin`
- `analyze_full_text`
- `full_text_max_chars`

Storage and output:

- `download_pdfs`
- `pdf_download_mode`
- `output_csv`
- `output_json`
- `output_markdown`
- `output_sqlite_exports`
- `data_dir`
- `papers_dir`
- `relevant_pdfs_dir`
- `results_dir`
- `database_path`

Runtime and logging:

- `run_mode`
- `verbosity`
- `max_workers`
- `request_timeout_seconds`
- `resume_mode`
- `disable_progress_bars`
- `log_http_requests`
- `log_http_payloads`
- `log_llm_prompts`
- `log_llm_responses`
- `log_screening_decisions`

## Error Handling And Stop Behavior

The GUI surfaces operational problems through:

- validation pop-ups for invalid config
- path pop-ups for missing output or file targets
- run failure pop-ups when a worker raises an exception
- stop warnings when a run ends due to a user stop request

`Force Stop` is a controlled stop, not a kill switch. A running HTTP request or model call may need a moment to finish before shutdown completes.

## Testing And Quality

Run the complete suite:

```powershell
py -3 -m unittest discover -s tests -v
```

Run lint:

```powershell
py -3 -m ruff check .
```

Run compile validation:

```powershell
py -3 -m compileall .
```

Measure app-code coverage:

```powershell
py -3 -m coverage run -m unittest discover -s tests -v
py -3 -m coverage report -m --omit "tests/*"
py -3 -m coverage html -d results\coverage_html_app --omit "tests/*"
```

Generate a JaCoCo-style detailed coverage bundle:

```powershell
py -3 coverage_report.py
```

Generate the stricter app-code gate used for release checks:

```powershell
py -3 coverage_report.py --top-files 25 --fail-under 99
```

Generate the full-repository report, including `tests/`:

```powershell
py -3 coverage_report.py --include-tests --results-dir results\coverage_report_all --top-files 25 --fail-under 99
```

That writes:

- `results/coverage_report/coverage_report.txt`
- `results/coverage_report/coverage_report.md`
- `results/coverage_report/coverage_summary.json`
- `results/coverage_report/html/index.html`
- `results/coverage_report_all/coverage_report.txt`
- `results/coverage_report_all/coverage_report.md`
- `results/coverage_report_all/coverage_summary.json`
- `results/coverage_report_all/html/index.html`

Offline deterministic smoke test:

```powershell
py -3 main.py --config-file tests\fixtures\offline_config.json
```

The HTML coverage report is written to:

- `results/coverage_html_app/index.html`

## Known Boundaries

- Semantic Scholar can return `429` rate-limit errors on public quotas
- Google Scholar and ResearchGate are import-based, not live-query integrations
- Springer live discovery requires a valid API key
- local Hugging Face inference depends on the installed runtime and available hardware
- full-text extraction depends on PDF availability and optional `pypdf`

## Recommended Workflow

For everyday use:

1. Start with the guided UI.
2. Fill in topic, research question, objective, and include/exclude criteria.
3. Choose sources and discovery breadth.
4. Set model provider or pass chain.
5. Decide whether you want metadata-only collection or full analysis.
6. Choose where results, database files, and PDFs should go.
7. Run with `verbose` first when tuning.
8. Save the setup as a profile for later reuse.

For repeatable research runs:

1. save a JSON config or GUI profile
2. run headless from CLI
3. archive the generated CSV/JSON/SQLite outputs with the run config snapshot

