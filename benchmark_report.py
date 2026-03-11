"""Generate repeatable benchmark summaries for local performance regressions."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from config import ResearchConfig
from discovery.fixture_client import FixtureDiscoveryClient
from discovery.manual_import_client import ManualImportClient
from models.paper import PaperMetadata
from utils.deduplication import deduplicate_papers
from utils.text_processing import build_query

BenchmarkCallable = Callable[[Path], int]


@dataclass(slots=True)
class BenchmarkCase:
    """Define one benchmark workload and the baseline threshold used to judge regressions."""

    name: str
    description: str
    max_seconds: float
    runner: BenchmarkCallable


@dataclass(slots=True)
class BenchmarkResult:
    """Store the measured timing details for one benchmark case."""

    name: str
    description: str
    max_seconds: float
    average_seconds: float
    median_seconds: float
    min_seconds: float
    max_observed_seconds: float
    iterations_completed: int
    regressed: bool


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the benchmark report helper."""

    parser = argparse.ArgumentParser(description="Run local benchmark fixtures and create a regression report")
    parser.add_argument(
        "--baseline-file",
        default="configs/benchmark_baselines.json",
        help="JSON file that defines benchmark thresholds and descriptions",
    )
    parser.add_argument(
        "--results-dir",
        default="results/benchmark_report",
        help="Directory where benchmark reports should be written",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="How many timed measurements to collect per benchmark",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=25,
        help="How many workload iterations each timed measurement should perform",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="How many untimed warmup runs to execute before measuring a benchmark",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with code 2 when any benchmark average exceeds its configured threshold",
    )
    return parser


def load_benchmark_baselines(path: Path) -> dict[str, dict[str, Any]]:
    """Load benchmark metadata and thresholds from a JSON baseline file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Benchmark baseline file must contain a JSON object")
    normalized: dict[str, dict[str, Any]] = {}
    for name, details in payload.items():
        if not isinstance(details, dict):
            raise ValueError(f"Benchmark baseline '{name}' must map to an object")
        normalized[name] = details
    return normalized


def build_default_cases(baselines: dict[str, dict[str, Any]]) -> list[BenchmarkCase]:
    """Build the benchmark registry from the shared baseline file."""

    return [
        _build_case(
            baselines,
            "fixture_discovery_search",
            _benchmark_fixture_discovery_search,
        ),
        _build_case(
            baselines,
            "deduplicate_fixture_batch",
            _benchmark_deduplicate_fixture_batch,
        ),
        _build_case(
            baselines,
            "manual_import_csv_load",
            _benchmark_manual_import_csv_load,
        ),
        _build_case(
            baselines,
            "query_variant_building",
            _benchmark_query_variant_building,
        ),
    ]


def _build_case(
        baselines: dict[str, dict[str, Any]],
        name: str,
        runner: BenchmarkCallable,
) -> BenchmarkCase:
    """Construct a benchmark case from the shared baseline configuration."""

    baseline = baselines.get(name)
    if baseline is None:
        raise KeyError(f"Missing baseline configuration for benchmark '{name}'")
    return BenchmarkCase(
        name=name,
        description=str(baseline.get("description", name.replace("_", " "))),
        max_seconds=float(baseline["max_seconds"]),
        runner=runner,
    )


def run_benchmark_suite(
        cases: Sequence[BenchmarkCase],
        *,
        project_root: Path,
        repeat: int,
        iterations: int,
        warmup: int,
) -> list[BenchmarkResult]:
    """Execute each benchmark case and return stable summary measurements."""

    results: list[BenchmarkResult] = []
    for case in cases:
        for _ in range(max(warmup, 0)):
            case.runner(project_root)

        measurements: list[float] = []
        for _ in range(max(repeat, 1)):
            started = time.perf_counter()
            completed = 0
            for _ in range(max(iterations, 1)):
                completed += int(case.runner(project_root))
            measurements.append(time.perf_counter() - started)

        average_seconds = statistics.fmean(measurements)
        results.append(
            BenchmarkResult(
                name=case.name,
                description=case.description,
                max_seconds=case.max_seconds,
                average_seconds=average_seconds,
                median_seconds=statistics.median(measurements),
                min_seconds=min(measurements),
                max_observed_seconds=max(measurements),
                iterations_completed=completed,
                regressed=average_seconds > case.max_seconds,
            )
        )
    return results


def build_report_artifacts(results: Sequence[BenchmarkResult]) -> tuple[str, str, dict[str, Any]]:
    """Render Markdown, plain text, and JSON summaries for benchmark results."""

    regressed = [result for result in results if result.regressed]
    markdown_lines = [
        "# Benchmark Report",
        "",
        f"- Benchmarks executed: `{len(results)}`",
        f"- Regressions detected: `{len(regressed)}`",
        "",
        "| Benchmark | Average (s) | Median (s) | Threshold (s) | Status |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    text_lines = [
        "Benchmark Report",
        f"Benchmarks executed: {len(results)}",
        f"Regressions detected: {len(regressed)}",
        "",
        "Benchmarks:",
    ]
    json_payload: dict[str, Any] = {
        "summary": {
            "benchmarks_executed": len(results),
            "regressions_detected": len(regressed),
        },
        "benchmarks": [],
    }

    for result in results:
        status = "REGRESSION" if result.regressed else "OK"
        markdown_lines.append(
            f"| `{result.name}` | `{result.average_seconds:.4f}` | `{result.median_seconds:.4f}` | "
            f"`{result.max_seconds:.4f}` | `{status}` |"
        )
        text_lines.append(
            f"- {result.name}: avg={result.average_seconds:.4f}s, median={result.median_seconds:.4f}s, "
            f"threshold={result.max_seconds:.4f}s, status={status}"
        )
        json_payload["benchmarks"].append(
            {
                "name": result.name,
                "description": result.description,
                "average_seconds": round(result.average_seconds, 6),
                "median_seconds": round(result.median_seconds, 6),
                "min_seconds": round(result.min_seconds, 6),
                "max_observed_seconds": round(result.max_observed_seconds, 6),
                "threshold_seconds": round(result.max_seconds, 6),
                "iterations_completed": result.iterations_completed,
                "regressed": result.regressed,
            }
        )

    if not results:
        markdown_lines.append("| _No benchmarks executed_ | `0.0000` | `0.0000` | `0.0000` | `OK` |")
        text_lines.append("- No benchmarks executed")

    return "\n".join(markdown_lines) + "\n", "\n".join(text_lines) + "\n", json_payload


def run_benchmark_report(
        argv: Sequence[str] | None = None,
        *,
        cases: Sequence[BenchmarkCase] | None = None,
) -> int:
    """Execute benchmark fixtures, write report artifacts, and optionally fail on regressions."""

    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(__file__).resolve().parent
    baseline_file = (project_root / args.baseline_file).resolve()
    results_dir = (project_root / args.results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    baselines = load_benchmark_baselines(baseline_file)
    selected_cases = list(cases) if cases is not None else build_default_cases(baselines)
    results = run_benchmark_suite(
        selected_cases,
        project_root=project_root,
        repeat=args.repeat,
        iterations=args.iterations,
        warmup=args.warmup,
    )
    markdown_report, text_report, json_payload = build_report_artifacts(results)

    markdown_path = results_dir / "benchmark_report.md"
    text_path = results_dir / "benchmark_report.txt"
    summary_path = results_dir / "benchmark_summary.json"
    csv_path = results_dir / "benchmark_results.csv"

    markdown_path.write_text(markdown_report, encoding="utf-8")
    text_path.write_text(text_report, encoding="utf-8")
    summary_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
    _write_results_csv(csv_path, results)

    print(text_report.strip())
    print()
    print(f"Markdown report: {markdown_path}")
    print(f"JSON summary: {summary_path}")
    print(f"CSV results: {csv_path}")

    if args.fail_on_regression and any(result.regressed for result in results):
        print("Benchmark regression detected.", file=sys.stderr)
        return 2

    return 0


def _write_results_csv(path: Path, results: Sequence[BenchmarkResult]) -> None:
    """Write the benchmark summary table to CSV for spreadsheet review."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "name",
                "description",
                "average_seconds",
                "median_seconds",
                "min_seconds",
                "max_observed_seconds",
                "threshold_seconds",
                "iterations_completed",
                "regressed",
            ],
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "name": result.name,
                    "description": result.description,
                    "average_seconds": f"{result.average_seconds:.6f}",
                    "median_seconds": f"{result.median_seconds:.6f}",
                    "min_seconds": f"{result.min_seconds:.6f}",
                    "max_observed_seconds": f"{result.max_observed_seconds:.6f}",
                    "threshold_seconds": f"{result.max_seconds:.6f}",
                    "iterations_completed": result.iterations_completed,
                    "regressed": result.regressed,
                }
            )


def _benchmark_fixture_discovery_search(project_root: Path) -> int:
    """Benchmark fixture-backed discovery normalization."""

    config = _build_temp_config(project_root)
    client = FixtureDiscoveryClient(config)
    return len(client.search())


def _benchmark_deduplicate_fixture_batch(project_root: Path) -> int:
    """Benchmark DOI and title deduplication on an amplified local fixture batch."""

    papers = _load_fixture_papers(project_root)
    amplified = [paper.model_copy() for _ in range(10) for paper in papers]
    deduplicated = deduplicate_papers(amplified, title_similarity_threshold=0.9)
    return len(deduplicated)


def _benchmark_manual_import_csv_load(project_root: Path) -> int:
    """Benchmark CSV import normalization using a local export fixture."""

    config = _build_temp_config(project_root)
    client = ManualImportClient(
        config,
        path=project_root / "tests" / "fixtures" / "researchgate_import.csv",
        source_name="researchgate_import",
    )
    return len(client.search())


def _benchmark_query_variant_building(project_root: Path) -> int:
    """Benchmark repeated discovery-query construction for complex search prompts."""

    _ = project_root
    query = build_query(
        "large language models systematic review automation",
        ["llm", "prisma", "screening", "benchmark"],
        boolean_expression="AND",
    )
    return len(query)


def _build_temp_config(project_root: Path) -> ResearchConfig:
    """Create an isolated benchmark configuration that uses local fixture data only."""

    root = project_root / "data" / "benchmark_runtime"
    config = ResearchConfig(
        research_topic="Benchmark fixture workload",
        search_keywords=["llm", "screening"],
        fixture_data_path=project_root / "tests" / "fixtures" / "offline_papers.json",
        disable_progress_bars=True,
        pages_to_retrieve=1,
        results_per_page=5,
        data_dir=root / "data",
        papers_dir=root / "papers",
        relevant_pdfs_dir=root / "papers" / "relevant",
        results_dir=root / "results",
        database_path=root / "data" / "benchmark.db",
    )
    return config.finalize()


def _load_fixture_papers(project_root: Path) -> list[PaperMetadata]:
    """Load the shared offline paper fixture into validated paper models."""

    payload = json.loads((project_root / "tests" / "fixtures" / "offline_papers.json").read_text(encoding="utf-8"))
    return [PaperMetadata(**item) for item in payload]


def main() -> None:
    """Run the benchmark report helper as a top-level script."""

    raise SystemExit(run_benchmark_report())


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    main()
