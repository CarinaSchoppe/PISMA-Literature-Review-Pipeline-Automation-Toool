# Product Roadmap

This document captures the practical target state for the PRISMA Literature Review Pipeline.

The goal is not vague "perfect automation". The goal is a strong, testable, maintainable research system that is:

- reproducible
- configurable
- explainable
- performant enough for real review work
- safe around provider limits and platform boundaries

## Current State

Already implemented and verified:

- guided desktop GUI and classic console wizard
- CLI, JSON config, and GUI parity for runtime configuration
- SQLite persistence and screening cache
- discovery through official APIs, bounded live HTML traversal, and manual import adapters
- live discovery toggles for OpenAlex, Semantic Scholar, Crossref, Springer, arXiv, PubMed, Europe PMC, CORE, and Google Scholar
- import adapters for Google Scholar exports, ResearchGate exports, generic CSV or JSON metadata files, and offline fixtures
- DOI and title-similarity deduplication
- backward and forward citation snowballing
- PDF enrichment and optional PDF download routing
- multi-pass screening with provider chaining
- heuristic, OpenAI-compatible, Gemini, Ollama, and local Hugging Face screening
- local MiniLM semantic topic prefiltering with configurable thresholds and optional automatic low-relevance filtering
- included and excluded outputs with rationale
- PRISMA-style flow output
- normal, verbose, and ultra-verbose logging
- controlled stop handling
- per-source rate limiting controls
- stage-specific worker overrides
- smarter request backoff on `429`, including `Retry-After` support and bounded exponential fallback
- persistent source-response cache for eligible GET requests
- incremental report regeneration that skips unchanged artifacts
- partial rerun modes for downstream-only execution
- batch PDF acquisition queueing
- optional async orchestration for network-heavy stages
- pre-run query reset and screening-cache reset controls
- `pyproject.toml` unification
- MyPy type-checking on the core backend and tooling surface
- CI pipeline for lint, type-checking, tests, coverage, and benchmark smoke checks
- benchmark fixtures for performance regressions
- provider-contract tests
- verified automated quality gates with total code coverage above `99%`

## Design Principles

All future work should preserve these rules:

- API-first where official APIs exist
- import-based fallback where live access is unstable or unsupported
- no hidden second code path for GUI logic
- explainable screening decisions
- reproducible config snapshots
- clear provider boundaries and secret handling
- strong automated tests before feature growth

## What "Better" Means For This Project

The product should move toward:

- broader but still reliable discovery coverage
- stronger research synthesis outputs
- clearer evidence trails for every decision
- richer visual reporting
- faster reruns through caching and resume controls
- more polished GUI ergonomics
- easier source onboarding through stable adapters and configuration-first toggles
- stronger operator confidence through explicit health, audit, and recovery tools

## Operator Configuration Vision

The system should remain operator-driven rather than hard-coded around one workflow.

That means a researcher should be able to choose, without touching code:

- which discovery sources are active
- which imports are used
- which AI provider or pass chain is used
- whether discovery is skipped
- whether PDFs are downloaded
- where the main database, result exports, caches, and PDF folders live
- how aggressive request concurrency and request pacing should be
- whether to rerun only reporting, screening, or PDF-sensitive stages
- whether response caching and incremental artifact regeneration are enabled
- whether the run should favor compact UI ergonomics or full advanced controls

The same controls should remain available through:

- GUI
- CLI flags
- JSON config files
- saved GUI profiles

## Discovery Roadmap

### Keep and deepen

- OpenAlex
- Crossref
- Semantic Scholar
- Springer
- arXiv
- PubMed
- Europe PMC
- CORE

### Add through stable providers or sanctioned metadata channels

- DataCite
- Lens.org metadata exports or official API access if the operational terms remain compatible
- institutional repository adapters where stable metadata APIs exist
- DOI landing-page enrichment when it improves metadata without turning the system into a brittle browser crawler

### Supported by live bounded traversal or import adapters

- Google Scholar live result traversal with explicit page-depth controls
- Google Scholar exports
- ResearchGate exports
- RIS exports
- BibTeX exports
- generic CSV and JSON metadata dumps
- fixture datasets for tests

### Not the default direction

Unbounded scraping of ResearchGate and arbitrary publisher pages should not be treated as the mainline architecture. Google Scholar support in this project is intentionally bounded, throttled, and operator-controlled rather than open-ended crawling.

Why:

- unstable HTML
- rate limiting and bot detection
- fragile tests
- policy and terms-of-service risk
- lower reproducibility than official APIs or exports

If broader intake is needed, the better direction is:

- more import adapters
- RIS and BibTeX import
- DOI landing-page enrichment
- publisher metadata APIs where available
- user-supplied source definitions that stay inside documented metadata endpoints instead of arbitrary scraping

## Screening And Synthesis Roadmap

### Already present

- thresholded include / maybe / exclude logic
- pass chaining
- provider-specific model selection
- rationale capture
- cached results to avoid unnecessary repeat screening

### Next high-value additions

- document-type classification:
  - primary study
  - review
  - editorial
  - correction
  - protocol
  - benchmark paper
- study-design extraction
- method taxonomy extraction
- dataset / benchmark extraction
- stronger evidence summarization per paper
- cross-paper synthesis tables
- evidence gap extraction
- contradiction and agreement detection across retained papers

### Structured synthesis outputs to add

- evidence matrix CSV
- benchmark matrix CSV
- methods taxonomy JSON
- claim-to-source traceability table
- themed narrative synthesis report

## Visualization Roadmap

Desired reporting additions:

- source contribution chart
- inclusion / exclusion reason chart
- publication year histogram
- venue frequency chart
- citation count distribution
- provider usage summary
- pass-chain outcome chart
- PRISMA flow visualization image export
- citation network visualization
- keyword co-occurrence graph
- retained-versus-rejected threshold distribution view
- per-provider latency and cache-hit chart for runtime diagnostics

Preferred output formats:

- CSV for tabular reuse
- JSON for downstream processing
- Markdown for readable summaries
- image exports for charts

## GUI Roadmap

Already present:

- settings pages
- handbook tab
- hover help
- output/result tabs
- force stop
- pass-chain editing
- compact versus advanced settings density modes
- grouped storage/path configuration
- export preview before run
- artifact browser with open actions
- chart preview tab
- run history tab
- screening audit tab
- provider health indicators
- scrollable settings pages and scrollable inspector tabs
- collapsible workspace and settings overview blocks for smaller windows
- responsive compact-window behavior so the workbench remains usable without fullscreen

Next GUI improvements:

- saved inspector layouts and window density presets
- richer chart interactions such as filtering and export-to-image controls
- clearer provider-specific credential cards with inline validation status
- more progressive disclosure so rarely used runtime knobs stay hidden until needed
- stronger path presets for "single-folder", "separate review bundle", and "database-first" workflows
- more polished visual styling within Tkinter limits, especially for summary cards and status badges

## Performance Roadmap

Already present:

- parallel workers
- stage-specific worker overrides
- resume mode
- fixture mode
- configurable request timeout
- per-source rate limiting controls
- pre-run query reset and screening-cache reset controls
- optional async orchestration for network-heavy stages
- batch PDF queueing
- persistent source-response cache
- smarter `429` handling with bounded backoff
- partial rerun modes and incremental report regeneration

Next performance work:

- async-native provider clients where upstream SDKs make that worth the extra complexity
- response-cache invalidation policies per source family
- warm-cache versus cold-cache benchmark fixtures
- workstation versus lightweight-laptop runtime profiles
- deeper measurement of source-specific latency, cache-hit rates, and PDF queue throughput
- more adaptive worker defaults based on source mix and local hardware

## Quality Roadmap

The project should remain:

- test-first for new public behavior
- coverage-protected above `99%`
- lint-clean
- modular and documented

Future quality additions:

- targeted UI type-checking once the Tkinter event layer is split into smaller typed helpers
- persisted benchmark trend history across environments
- targeted soak tests for async and batched runtime paths
- broader source-fixture matrices for provider-edge-case parsing
- stricter mutation-style checks on screening and export invariants
- richer screenshot-style GUI regression checks where practical
- clearer operator-facing guidance around production-only versus whole-tree coverage reports so coverage output is harder to misread

## Provider Strategy

Hosted providers:

- OpenAI-compatible
- Gemini

Local providers:

- Ollama
- Hugging Face local models

Good practical defaults:

- strongest hosted: `gpt-5.4`
- strong Google-hosted: `gemini-2.5-flash`
- easiest local: `qwen3:8b` on Ollama
- strongest default local open-weight choice in this project: `Qwen/Qwen3-14B`

Future provider ideas:

- Azure OpenAI-compatible config profile
- Anthropic-compatible adapter if the product scope expands
- model presets for fast / balanced / strongest
- clearer preset bundles for literature-review use cases such as "broad recall", "strict inclusion", and "biomedical review"

## Research Workflow Vision

The desired end-state workflow is:

1. Define topic, question, and criteria.
2. Choose sources, discovery depth, and result caps.
3. Pull metadata from stable APIs and imports.
4. Deduplicate and persist.
5. Expand citations where useful.
6. Download PDFs according to policy.
7. Run one or more screening passes.
8. Keep full rationale for retained and rejected papers.
9. Generate structured exports, synthesis tables, and visual summaries.
10. Re-run later with the same config and get consistent, traceable results.

## Boundaries We Should Keep

We should not optimize for:

- brittle browser scraping as the main ingestion path
- opaque screening decisions
- provider-specific behavior hidden outside config
- giant monolithic UI logic with duplicated state
- one-off features that break testability or reproducibility

## Recommended Next Milestones

### Milestone 1

- add RIS and BibTeX imports
- add document-type classification
- add evidence matrix export
- add chart generation for PRISMA and inclusion reasons
- add DataCite discovery support if the metadata quality justifies the maintenance cost

### Milestone 2

- add stronger synthesis reporting
- add richer source-health diagnostics and credential validation
- add saved workspace layouts and operator presets
- add DOI landing-page enrichment safeguards

### Milestone 3

- add benchmark/dataset extraction
- add claim-to-source traceability exports
- add richer citation graph and keyword co-occurrence visualizations
- add longer-running soak and concurrency tests

## How To Judge A New Feature

A new feature is worth adding when it improves at least one of these:

- recall
- screening quality
- reproducibility
- interpretability
- speed
- auditability

And it should not seriously damage these:

- testability
- maintainability
- provider compliance
- user clarity


