"""Generate a JaCoCo-style coverage bundle for the Python test suite."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(slots=True)
class CoverageFileSummary:
    """Normalized coverage details for a single source file."""

    path: str
    statements: int
    covered_lines: int
    missing_lines: list[int]
    percent_covered: float

    @property
    def missing_count(self) -> int:
        """Return the number of missing executable lines for the file."""

        return len(self.missing_lines)

    @property
    def missing_ranges(self) -> str:
        """Return missing line numbers compressed into human-readable ranges."""

        return compress_line_ranges(self.missing_lines)


@dataclass(slots=True)
class CoverageSummary:
    """Aggregate coverage metrics plus the worst-covered files."""

    total_statements: int
    covered_lines: int
    missing_lines: int
    percent_covered: float
    files: list[CoverageFileSummary]


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the coverage report helper."""

    parser = argparse.ArgumentParser(description="Run tests and generate a detailed coverage report")
    parser.add_argument(
        "--results-dir",
        default="results/coverage_report",
        help="Directory where JSON, Markdown, text, and HTML coverage reports will be written",
    )
    parser.add_argument(
        "--top-files",
        type=int,
        default=20,
        help="Maximum number of low-coverage files to highlight in the Markdown and text summaries",
    )
    parser.add_argument(
        "--omit",
        action="append",
        default=None,
        help="Coverage omit pattern. Repeat to add multiple patterns. Defaults to tests/*",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests in the coverage report instead of omitting tests/*",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Optional minimum overall coverage percentage. The script exits with code 2 if unmet.",
    )
    return parser


def compress_line_ranges(line_numbers: Sequence[int]) -> str:
    """Compress sorted line numbers into a JaCoCo-like range string."""

    if not line_numbers:
        return "-"

    ordered = sorted(set(int(number) for number in line_numbers))
    ranges: list[str] = []
    start = previous = ordered[0]

    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(_format_range(start, previous))
        start = previous = number

    ranges.append(_format_range(start, previous))
    return ", ".join(ranges)


def _format_range(start: int, end: int) -> str:
    """Format a single line or inclusive line range."""

    if start == end:
        return str(start)
    return f"{start}-{end}"


def summarize_coverage_payload(payload: dict[str, Any]) -> CoverageSummary:
    """Convert raw coverage JSON output into a stable summary model."""

    files: list[CoverageFileSummary] = []
    for path, details in payload.get("files", {}).items():
        summary = details.get("summary", {})
        files.append(
            CoverageFileSummary(
                path=path,
                statements=int(summary.get("num_statements", 0)),
                covered_lines=int(summary.get("covered_lines", 0)),
                missing_lines=[int(line) for line in details.get("missing_lines", [])],
                percent_covered=float(summary.get("percent_covered", 0.0)),
            )
        )

    files.sort(key=lambda item: (item.percent_covered, -item.missing_count, item.path))

    totals = payload.get("totals", {})
    return CoverageSummary(
        total_statements=int(totals.get("num_statements", 0)),
        covered_lines=int(totals.get("covered_lines", 0)),
        missing_lines=int(totals.get("missing_lines", 0)),
        percent_covered=float(totals.get("percent_covered", 0.0)),
        files=files,
    )


def build_report_artifacts(
        summary: CoverageSummary,
        *,
        top_files: int,
        html_index_path: Path,
        raw_json_path: Path,
) -> tuple[str, str, dict[str, Any]]:
    """Render Markdown, text, and JSON-friendly summaries from normalized coverage data."""

    highlighted = summary.files[: max(top_files, 0)]
    markdown_lines = [
        "# Coverage Report",
        "",
        f"- Overall coverage: `{summary.percent_covered:.2f}%`",
        f"- Covered lines: `{summary.covered_lines}`",
        f"- Missing lines: `{summary.missing_lines}`",
        f"- Executable statements: `{summary.total_statements}`",
        f"- HTML report: `{html_index_path}`",
        f"- Raw JSON: `{raw_json_path}`",
        "",
        "## Lowest-Coverage Files",
        "",
        "| File | Coverage | Missing Lines | Missing Ranges |",
        "| --- | ---: | ---: | --- |",
    ]
    text_lines = [
        "Coverage Report",
        "===============",
        "Overall result:",
        f"- Overall coverage: {summary.percent_covered:.2f}%",
        f"- Covered executable lines: {summary.covered_lines}",
        f"- Missing executable lines: {summary.missing_lines}",
        f"- Executable statements considered: {summary.total_statements}",
        "",
        "Generated artifacts:",
        f"- HTML report for drill-down inspection: {html_index_path}",
        f"- Raw coverage JSON payload: {raw_json_path}",
        "",
        "Interpretation:",
        "- Higher percentages indicate that more real production code paths were exercised by tests.",
        "- The file list below is sorted from weakest coverage to strongest coverage.",
        "- Missing ranges show the exact executable lines that still need direct coverage.",
        "",
        "Lowest-Coverage Files:",
    ]
    json_summary: dict[str, Any] = {
        "overall": {
            "percent_covered": round(summary.percent_covered, 2),
            "covered_lines": summary.covered_lines,
            "missing_lines": summary.missing_lines,
            "num_statements": summary.total_statements,
        },
        "artifacts": {
            "html_index": str(html_index_path),
            "raw_json": str(raw_json_path),
        },
        "files": [],
    }

    for file_summary in highlighted:
        markdown_lines.append(
            f"| `{file_summary.path}` | `{file_summary.percent_covered:.2f}%` | "
            f"`{file_summary.missing_count}` | `{file_summary.missing_ranges}` |"
        )
        text_lines.append(
            f"- {file_summary.path}: {file_summary.percent_covered:.2f}% "
            f"({file_summary.missing_count} missing lines: {file_summary.missing_ranges})"
        )
        json_summary["files"].append(
            {
                "path": file_summary.path,
                "percent_covered": round(file_summary.percent_covered, 2),
                "covered_lines": file_summary.covered_lines,
                "num_statements": file_summary.statements,
                "missing_lines": file_summary.missing_lines,
                "missing_ranges": file_summary.missing_ranges,
            }
        )

    if not highlighted:
        markdown_lines.append("| _No files available_ | `0.00%` | `0` | `-` |")
        text_lines.append("- No files available")

    return "\n".join(markdown_lines) + "\n", "\n".join(text_lines) + "\n", json_summary


def run_coverage_report(argv: Sequence[str] | None = None) -> int:
    """Execute the tests under coverage and materialize detailed report artifacts."""

    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(__file__).resolve().parent
    results_dir = (project_root / args.results_dir).resolve()
    html_dir = results_dir / "html"
    raw_json_path = results_dir / "coverage.json"
    markdown_path = results_dir / "coverage_report.md"
    text_path = results_dir / "coverage_report.txt"
    summary_json_path = results_dir / "coverage_summary.json"
    junit_xml_path = results_dir / "junit.xml"
    pytest_output_path = results_dir / "pytest_terminal.txt"
    coverage_data_path = results_dir / ".coverage"
    coverage_config_path = results_dir / ".coveragerc"

    results_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    omit_patterns = [] if args.include_tests else (args.omit or ["tests/*"])
    python_executable = sys.executable
    coverage_env = os.environ.copy()
    coverage_env["COVERAGE_FILE"] = str(coverage_data_path)
    coverage_config_path.write_text(_build_coverage_config(omit_patterns), encoding="utf-8")

    fallback_used = False
    if _pytest_cov_is_available():
        report_result = _run_subprocess(
            _build_pytest_cov_command(
                python_executable=python_executable,
                coverage_config_path=coverage_config_path,
                raw_json_path=raw_json_path,
                html_dir=html_dir,
                junit_xml_path=junit_xml_path,
            ),
            cwd=project_root,
            env=coverage_env,
        )
        pytest_output = _format_subprocess_output(report_result)
    else:
        fallback_used = True
        report_result = _run_subprocess(
            _build_coverage_fallback_pytest_command(
                python_executable=python_executable,
                coverage_data_path=coverage_data_path,
                coverage_config_path=coverage_config_path,
                junit_xml_path=junit_xml_path,
            ),
            cwd=project_root,
            env=coverage_env,
        )
        pytest_output = (
            "Pytest-cov plugin was not available, so coverage_report.py used the built-in "
            "coverage.py fallback runner.\n\n"
            + _format_subprocess_output(report_result)
        )
        if coverage_data_path.exists():
            export_result, export_output = _export_coverage_artifacts_with_coverage_py(
                python_executable=python_executable,
                coverage_data_path=coverage_data_path,
                coverage_config_path=coverage_config_path,
                raw_json_path=raw_json_path,
                html_dir=html_dir,
                cwd=project_root,
                env=coverage_env,
            )
            if export_output:
                pytest_output = f"{pytest_output}\n\n[coverage.py export]\n{export_output}".strip()
            if export_result.returncode != 0 and not raw_json_path.exists():
                report_result = export_result

    pytest_output_path.write_text(pytest_output + "\n", encoding="utf-8")

    if int(getattr(report_result, "returncode", 0)) != 0 and not raw_json_path.exists():
        print("Pytest execution transcript")
        print("=========================")
        print(pytest_output.strip())
        print()
        print("Generated artifacts")
        print("===================")
        print(f"Pytest terminal log: {pytest_output_path}")
        if fallback_used:
            print(
                "Coverage.py fallback mode was used, but coverage artifacts could still not be generated.",
                file=sys.stderr,
            )
        elif "--cov=." in pytest_output and "unrecognized arguments" in pytest_output:
            print(
                "Pytest-cov does not appear to be installed in the active environment. "
                "Install the development dependencies or explicitly install pytest-cov before running coverage_report.py.",
                file=sys.stderr,
            )
        print("Coverage report generation failed before coverage artifacts were written.", file=sys.stderr)
        return int(getattr(report_result, "returncode", 1))

    payload = json.loads(raw_json_path.read_text(encoding="utf-8"))
    summary = summarize_coverage_payload(payload)
    markdown_report, text_report, summary_json = build_report_artifacts(
        summary,
        top_files=args.top_files,
        html_index_path=html_dir / "index.html",
        raw_json_path=raw_json_path,
    )

    markdown_path.write_text(markdown_report, encoding="utf-8")
    text_path.write_text(text_report, encoding="utf-8")
    summary_json_path.write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    print("Pytest execution transcript")
    print("=========================")
    print(pytest_output.strip())
    print()
    print("Coverage execution summary")
    print("=========================")
    print(text_report.strip())
    print()
    print("Generated artifacts")
    print("===================")
    print(f"Markdown report: {markdown_path}")
    print(f"JSON summary: {summary_json_path}")
    print(f"HTML report: {html_dir / 'index.html'}")
    print(f"JUnit XML: {junit_xml_path}")
    print(f"Pytest terminal log: {pytest_output_path}")
    if args.fail_under is not None:
        # Print the threshold comparison explicitly so CI logs show both the configured gate
        # and the observed result without requiring the operator to open the report artifact.
        print(
            "Coverage threshold check: "
            f"required >= {float(args.fail_under):.2f}%, observed {summary.percent_covered:.2f}%"
        )
    else:
        print("Coverage threshold check: no fail-under threshold was requested for this run.")

    if args.fail_under is not None and summary.percent_covered < float(args.fail_under):
        print(
            f"Coverage threshold not met: {summary.percent_covered:.2f}% < {float(args.fail_under):.2f}%",
            file=sys.stderr,
        )
        return 2

    return 0


def main() -> None:
    """Run the coverage report helper as a top-level script."""

    raise SystemExit(run_coverage_report())


def _pytest_cov_is_available() -> bool:
    """Return whether `pytest-cov` is importable in the current Python environment."""

    return importlib.util.find_spec("pytest_cov") is not None


def _build_pytest_cov_command(
    *,
    python_executable: str,
    coverage_config_path: Path,
    raw_json_path: Path,
    html_dir: Path,
    junit_xml_path: Path,
) -> list[str]:
    """Build the preferred pytest command that relies on the `pytest-cov` plugin."""

    return [
        python_executable,
        "-m",
        "pytest",
        "-v",
        "--cov=.",
        f"--cov-config={coverage_config_path}",
        "--cov-report=term-missing:skip-covered",
        f"--cov-report=json:{raw_json_path}",
        f"--cov-report=html:{html_dir}",
        f"--junitxml={junit_xml_path}",
        "tests",
    ]


def _build_coverage_fallback_pytest_command(
    *,
    python_executable: str,
    coverage_data_path: Path,
    coverage_config_path: Path,
    junit_xml_path: Path,
) -> list[str]:
    """Build a fallback pytest command that runs under `coverage.py` directly."""

    return [
        python_executable,
        "-m",
        "coverage",
        "run",
        f"--data-file={coverage_data_path}",
        f"--rcfile={coverage_config_path}",
        "-m",
        "pytest",
        "-v",
        f"--junitxml={junit_xml_path}",
        "tests",
    ]


def _export_coverage_artifacts_with_coverage_py(
    *,
    python_executable: str,
    coverage_data_path: Path,
    coverage_config_path: Path,
    raw_json_path: Path,
    html_dir: Path,
    cwd: Path,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Export JSON and HTML coverage artifacts using the `coverage.py` CLI fallback."""

    json_result = _run_subprocess(
        [
            python_executable,
            "-m",
            "coverage",
            "json",
            f"--data-file={coverage_data_path}",
            f"--rcfile={coverage_config_path}",
            "-o",
            str(raw_json_path),
        ],
        cwd=cwd,
        env=env,
    )
    html_result = _run_subprocess(
        [
            python_executable,
            "-m",
            "coverage",
            "html",
            f"--data-file={coverage_data_path}",
            f"--rcfile={coverage_config_path}",
            "-d",
            str(html_dir),
        ],
        cwd=cwd,
        env=env,
    )
    outputs = [segment for segment in (_format_subprocess_output(json_result), _format_subprocess_output(html_result)) if segment]
    combined_output = "\n\n".join(outputs)
    return (html_result if html_result.returncode != 0 else json_result), combined_output


def _run_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run one subprocess in text mode and capture stdout/stderr for reporting."""

    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        env=env,
    )


def _format_subprocess_output(result: subprocess.CompletedProcess[str]) -> str:
    """Combine stdout and stderr into one readable transcript block."""

    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = stdout.strip()
    if stderr:
        output = f"{output}\n[stderr]\n{stderr}".strip()
    return output


def _build_coverage_config(omit_patterns: Sequence[str]) -> str:
    """Render a temporary coverage configuration used by pytest-cov."""

    run_lines = ["[run]", "branch = false", "source =", "    ."]
    report_lines = ["[report]", "precision = 2", "show_missing = true", "skip_covered = false"]
    if omit_patterns:
        omit_lines = [f"    {pattern}" for pattern in omit_patterns]
        run_lines.extend(["omit =", *omit_lines])
        report_lines.extend(["omit =", *omit_lines])
    return textwrap.dedent("\n".join([*run_lines, "", *report_lines, ""]))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    main()
