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
- discovery through official APIs and manual import adapters
- DOI and title-similarity deduplication
- backward and forward citation snowballing
- PDF enrichment and optional PDF download routing
- multi-pass screening with provider chaining
- heuristic, OpenAI-compatible, Gemini, Ollama, and local Hugging Face screening
- included and excluded outputs with rationale
- PRISMA-style flow output
- verbose and debug logging
- controlled stop handling
- `99.04%` app-code coverage excluding `tests/*`
- `99.09%` full-repository coverage including `tests/*`

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

## Discovery Roadmap

### Keep and deepen

- OpenAlex
- Crossref
- Semantic Scholar
- Springer
- arXiv
- PubMed

### Supported by import adapters

- Google Scholar exports
- ResearchGate exports
- generic CSV and JSON metadata dumps
- fixture datasets for tests

### Not the default direction

Direct scraping of Google Scholar, ResearchGate, and arbitrary publisher pages should not be treated as the mainline architecture.

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

Next GUI improvements:

- richer visual pass-chain builder
- compact vs advanced settings modes
- stronger grouped path configuration
- export preview before run
- artifact browser with open buttons and summaries
- chart preview tab
- run history tab
- screening audit tab
- provider health indicators

## Performance Roadmap

Already present:

- parallel workers
- resume mode
- fixture mode
- configurable request timeout

Next performance work:

- per-source rate limiting controls
- smarter request backoff on `429`
- persistent source-response cache
- incremental report regeneration
- partial rerun mode for only affected stages
- batch PDF acquisition queue
- optional async client layer for network-heavy stages

## Quality Roadmap

The project should remain:

- test-first for new public behavior
- coverage-protected above `99%`
- lint-clean
- modular and documented

Future quality additions:

- `pyproject.toml` unification
- type-checking with MyPy or Pyright
- CI pipeline for lint, tests, and coverage gates
- benchmark fixtures for performance regressions
- provider-contract tests

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

### Milestone 2

- add per-source rate-limit configuration
- add provider health/status indicators in the GUI
- add run history and audit trail tabs
- add stronger synthesis reporting

### Milestone 3

- add benchmark/dataset extraction
- add claim-to-source traceability exports
- add richer citation graph and keyword co-occurrence visualizations
- add CI and type-checking gates

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
