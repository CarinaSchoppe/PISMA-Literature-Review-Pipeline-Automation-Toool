# CLI Reference

This document is the command-line reference for the PRISMA Literature Review Pipeline.

For the full configuration surface, see [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md).
For the GUI workflow, see [GUI_GUIDE.md](GUI_GUIDE.md).

## Entry Points

Show the guided launcher:

```powershell
py -3 main.py
```

Open the desktop UI directly:

```powershell
py -3 main.py --ui
```

Open the classic console wizard:

```powershell
py -3 main.py --wizard
```

Run headless from flags:

```powershell
py -3 main.py --topic "LLM evaluation" --keywords "large language model,benchmark" --run-mode analyze
```

Run from a JSON configuration:

```powershell
py -3 main.py --config-file path\to\run_config.json
```

## Help Output

Show all supported flags:

```powershell
py -3 main.py --help
```

The CLI exposes the same underlying runtime settings as the GUI.

## Common Run Patterns

### Metadata collection only

```powershell
py -3 main.py ^
  --topic "AI governance" ^
  --keywords "AI governance,large language models,policy" ^
  --run-mode collect ^
  --results-dir results\governance_collect
```

### Full analysis run

```powershell
py -3 main.py ^
  --topic "Healthcare LLM evaluation" ^
  --research-question "How are LLM systems evaluated in healthcare decision support?" ^
  --keywords "healthcare llm,evaluation,benchmark,clinical decision support" ^
  --year-start 2020 ^
  --year-end 2026 ^
  --max-papers 60 ^
  --run-mode analyze ^
  --verbosity verbose
```

### Skip discovery and reuse stored papers

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --skip-discovery ^
  --run-mode analyze
```

### Regenerate reports only

```powershell
py -3 main.py ^
  --config-file tests\fixtures\offline_config.json ^
  --skip-discovery ^
  --partial-rerun-mode reporting_only
```

## Verbosity Modes

Use:

- `--verbosity normal`
- `--verbosity verbose`
- `--verbosity ultra_verbose`

Shortcuts:

- `--verbose`
- `--ultra-verbose`

Meaning:

`normal`

- major stage boundaries
- important outcomes
- warnings and failures

`verbose`

- all major steps
- source starts and finishes
- screening outcomes
- output writes

`ultra_verbose`

- detailed request and parsing traces
- retry and backoff events
- per-paper scoring details
- threshold comparisons
- timing-oriented diagnostics where implemented

Compatibility note:

- `debug` and `quiet` are still accepted by the parser
- the recommended operator-facing modes remain `normal`, `verbose`, and `ultra_verbose`

## Local MiniLM Semantic Relevance

Enable the local semantic topic gate:

```powershell
py -3 main.py ^
  --topic "AI governance in healthcare" ^
  --keywords "AI governance,healthcare,large language models" ^
  --topic-prefilter-enabled ^
  --topic-prefilter-filter-low-relevance ^
  --topic-prefilter-model sentence-transformers/all-MiniLM-L6-v2 ^
  --topic-prefilter-high-threshold 0.75 ^
  --topic-prefilter-review-threshold 0.55
```

Useful related flags:

- `--topic-prefilter-text-mode title_only`
- `--topic-prefilter-text-mode title_abstract`
- `--topic-prefilter-text-mode title_abstract_full_text`
- `--topic-prefilter-max-chars 4000`

## Google Scholar Page Depth

Enable bounded Google Scholar traversal:

```powershell
py -3 main.py ^
  --topic "AI evaluation" ^
  --keywords "large language model,evaluation,benchmark" ^
  --google-scholar-enabled ^
  --google-scholar-pages 5 ^
  --google-scholar-page-min 1 ^
  --google-scholar-page-max 25 ^
  --google-scholar-results-per-page 10 ^
  --google-scholar-calls-per-second 0.5
```

Notes:

- `google_scholar_pages` is validated against `--google-scholar-page-min` and `--google-scholar-page-max`
- larger values increase runtime and HTML traversal cost
- deduplication still happens after retrieval

## Guided GUI Defaults

These flags are mainly useful when you launch the desktop workbench from a saved script or shortcut:

```powershell
py -3 main.py ^
  --ui ^
  --ui-settings-mode advanced ^
  --ui-show-advanced-settings
```

## Semantic Scholar Rate-Limit Controls

Example of a safer public-quota configuration:

```powershell
py -3 main.py ^
  --semantic-scholar-enabled ^
  --semantic-scholar-max-requests-per-minute 20 ^
  --semantic-scholar-request-delay-seconds 1.5 ^
  --semantic-scholar-retry-attempts 4 ^
  --semantic-scholar-retry-backoff-strategy exponential ^
  --semantic-scholar-retry-backoff-base-seconds 2.0
```

## Output And Storage

Typical output configuration:

```powershell
py -3 main.py ^
  --output-csv ^
  --output-json ^
  --output-markdown ^
  --output-sqlite-exports ^
  --results-dir results\my_run ^
  --database-path data\my_run\pipeline.db ^
  --log-file-path results\my_run\pipeline.log
```

Typical PDF configuration:

```powershell
py -3 main.py ^
  --download-pdfs ^
  --pdf-download-mode relevant_only ^
  --papers-dir papers\all_pdfs ^
  --relevant-pdfs-dir papers\kept_pdfs
```

## Multi-Pass Screening

Example pass chain:

```powershell
py -3 main.py ^
  --analysis-pass "fast|huggingface_local|65|strict|8|Qwen/Qwen3-14B|0" ^
  --analysis-pass "review|gemini|80|triage|10|gemini-2.5-flash|65" ^
  --analysis-pass "final|openai_compatible|88|strict|5|gpt-5.4|80"
```

Each pass can set:

- provider
- threshold
- decision mode
- maybe margin
- model override
- minimum previous-pass score

## Testing And Coverage Commands

Run the test suite:

```powershell
py -3 -m pytest -v
```

Run lint:

```powershell
py -3 -m ruff check .
```

Run type-checking:

```powershell
py -3 -m mypy
```

Run the production-code coverage gate:

```powershell
py -3 coverage_report.py --results-dir results\coverage_report --top-files 25 --fail-under 99.5
```

Generate the optional whole-tree reference report:

```powershell
py -3 coverage_report.py --include-tests --results-dir results\coverage_report_all --top-files 25
```

Why the file list can differ:

- `python -m coverage report` follows the coverage configuration in `pyproject.toml`
- by default that configuration omits `tests/*`
- if you want test modules to appear too, rerun coverage with `coverage_report.py --include-tests ...`
