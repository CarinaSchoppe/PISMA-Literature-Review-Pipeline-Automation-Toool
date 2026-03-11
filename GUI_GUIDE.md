# GUI Guide

This guide describes the guided desktop workbench.

The GUI edits the same validated runtime configuration used by the CLI. Nothing in the GUI is a separate pipeline implementation.

## Starting The GUI

Open the launcher:

```powershell
py -3 main.py
```

Open the GUI directly:

```powershell
py -3 main.py --ui
```

## Layout

The desktop workbench is organized into:

- a top toolbar for run actions
- a `Settings` tab for configuration
- result and audit tabs for outputs and review inspection
- a built-in handbook tab

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

## Settings Shell

The `Settings` tab uses a three-pane layout:

- left navigation rail
- center settings editor
- right inspector

The workbench also includes two large overview sections:

- a workspace overview near the top of the window
- a settings overview inside the `Settings` tab

Both overview sections can be collapsed manually so the actual working area gets more room.

Settings pages:

- `Review Setup`
- `Discovery`
- `AI Screening`
- `Connections and Keys`
- `Storage and Output`
- `Advanced Runtime`

Inspector tabs:

- `Find`
- `Quick Edit`
- `Guides`
- `Summary`

## Scroll Behavior

The GUI is designed to stay usable on smaller windows.

Scrollable areas include:

- settings pages
- quick-edit inspector
- summary inspector
- run log
- paper tables
- handbook tree and handbook text
- artifact browser
- chart preview
- run history
- screening audit

If a page grows beyond the visible window size, vertical scrolling keeps the content reachable. Wide tables and wide content areas also expose horizontal scrolling where needed.

Non-fullscreen usability:

- when the window becomes smaller, the workbench automatically switches into a more compact layout
- pane defaults narrow so the center editing canvas gets more room
- oversized overview blocks are hidden automatically in compact-window situations
- the pages themselves remain scrollable, so you can keep working without maximizing the app

## Compact And Advanced Modes

The GUI supports two density modes:

- `Compact`
  - reduces explanatory text density
- `Advanced`
  - restores full helper text and advanced controls

`Show advanced settings` reveals lower-level runtime controls only when needed.

Saved GUI profiles also persist:

- `Compact` vs `Advanced` settings density
- whether advanced settings pages open immediately or stay hidden until requested

## Input Guidance

Relevant text-entry fields include:

- placeholder examples
- hover help
- focus help
- validation for malformed inputs

Keyword-like fields accept:

- commas
- semicolons
- line breaks

Examples shown in the GUI are valid inputs, not decorative text.

## Review Setup Page

Use this page for:

- research topic
- research question
- review objective
- keywords
- Boolean operators
- inclusion criteria
- exclusion criteria
- banned topics
- excluded title terms

## Discovery Page

Use this page for:

- discovery source toggles
- year boundaries
- discovery breadth
- max and min discovered record limits
- Google Scholar page depth
- HTTP cache settings
- retry controls

The Google Scholar controls are available here and in quick edit:

- numeric page-depth control
- slider for page depth
- configurable minimum and maximum page-depth bounds for stricter saved operator profiles

## AI Screening Page

Use this page for:

- primary screening provider
- thresholds
- decision mode
- maybe margin
- local MiniLM topic prefilter
- full-text analysis
- pass-chain editing

The pass-chain builder is visual and allows:

- add pass
- duplicate pass
- reorder passes
- set provider-specific model overrides
- set minimum previous-pass score

## Connections And Keys Page

Use this page for:

- API keys
- provider base URLs
- contact email settings
- provider-specific request pacing controls

Typical fields include:

- OpenAI-compatible key and base URL
- Gemini key and base URL
- Ollama base URL
- Springer API key
- CORE API key
- Crossref mailto
- Unpaywall email

## Storage And Output Page

Use this page for:

- results directory
- database path
- PDF storage paths
- output toggles
- persistent log file path

Common switches:

- `Write CSV exports`
- `Write JSON exports`
- `Write Markdown summary`
- `Write SQLite exports`
- `Download paper PDFs`

## Advanced Runtime Page

Use this page for:

- run mode
- verbosity
- worker counts
- partial rerun mode
- resume and reset controls
- progress-bar control
- detailed logging toggles

## Run Actions

Toolbar actions:

- `Start Run`
- `Analyze Stored Results`
- `Force Stop`

`Analyze Stored Results`

- skips new discovery
- reuses papers already stored in the active database

`Force Stop`

- requests a controlled stop
- stops at safe boundaries rather than killing the process instantly

## Window-Size Tips

If the workbench feels crowded:

1. Collapse the workspace overview.
2. Collapse the settings overview.
3. Keep the app in `Compact` mode.
4. Use the scrollable `Quick Edit` panel for frequent changes instead of expanding every settings page.

## Result Tabs

`Run Log`

- live logs from the active run
- mirrors the configured verbosity level

`All Papers`

- full discovered or analyzed paper list

`Included`

- papers retained after screening

`Excluded`

- papers rejected after screening

`Outputs`

- artifact browser
- summaries
- open-file and open-folder actions

`Charts`

- quick visual summaries of screening decisions and source mix

`Run History`

- recent run history with status and artifact locations

`Screening Audit`

- retain reasons
- exclusion reasons
- extracted passages
- explanation details

## Provider Health Indicators

The GUI shows provider-health summaries so you can see whether a source or AI backend is:

- ready
- disabled
- missing credentials
- otherwise not available for the current configuration

## Error Handling

The GUI uses pop-up dialogs for:

- invalid configuration
- bad paths
- failed runs
- stopped runs

These dialogs are intended to tell you what failed and where to look next, not just that “something went wrong.”

## Recommended GUI Workflow

1. Start with `Review Setup`.
2. Choose your sources on `Discovery`.
3. Add screening logic on `AI Screening`.
4. Fill in provider credentials on `Connections and Keys`.
5. Confirm export locations on `Storage and Output`.
6. Use `Advanced Runtime` only for tuning and diagnostics.
7. Save the profile once the setup is stable.
