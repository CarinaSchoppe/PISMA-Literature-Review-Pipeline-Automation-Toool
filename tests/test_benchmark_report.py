"""Tests for the benchmark regression reporting helper."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark_report


class BenchmarkReportTests(unittest.TestCase):
    """Exercise benchmark baselines, execution, and artifact generation."""

    def test_load_benchmark_baselines_validates_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid_path = root / "valid.json"
            valid_path.write_text(
                json.dumps({"fixture_discovery_search": {"description": "Fixture", "max_seconds": 1.5}}),
                encoding="utf-8",
            )
            loaded = benchmark_report.load_benchmark_baselines(valid_path)
            self.assertIn("fixture_discovery_search", loaded)

            invalid_root = root / "invalid_root.json"
            invalid_root.write_text(json.dumps([]), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark_report.load_benchmark_baselines(invalid_root)

            invalid_item = root / "invalid_item.json"
            invalid_item.write_text(json.dumps({"fixture_discovery_search": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark_report.load_benchmark_baselines(invalid_item)

    def test_build_default_cases_uses_named_baselines(self) -> None:
        baselines = {
            "fixture_discovery_search": {"description": "Fixture", "max_seconds": 1.0},
            "deduplicate_fixture_batch": {"description": "Deduplicate", "max_seconds": 1.0},
            "manual_import_csv_load": {"description": "Manual import", "max_seconds": 1.0},
            "query_variant_building": {"description": "Queries", "max_seconds": 1.0},
        }

        cases = benchmark_report.build_default_cases(baselines)

        self.assertEqual([case.name for case in cases], list(baselines))
        self.assertTrue(all(callable(case.runner) for case in cases))

    def test_run_benchmark_suite_computes_summary_and_regression_flags(self) -> None:
        calls: list[str] = []

        def fake_runner(_project_root: Path) -> int:
            calls.append("run")
            return 5

        case = benchmark_report.BenchmarkCase(
            name="fixture_discovery_search",
            description="Fixture benchmark",
            max_seconds=1.0,
            runner=fake_runner,
        )

        with patch(
            "benchmark_report.time.perf_counter",
            side_effect=[0.0, 1.1, 2.0, 3.4],
        ):
            results = benchmark_report.run_benchmark_suite(
                [case],
                project_root=Path.cwd(),
                repeat=2,
                iterations=3,
                warmup=1,
            )

        self.assertEqual(len(calls), 7)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0].average_seconds, 1.25)
        self.assertTrue(results[0].regressed)
        self.assertEqual(results[0].iterations_completed, 15)

    def test_build_report_artifacts_renders_markdown_text_and_json(self) -> None:
        results = [
            benchmark_report.BenchmarkResult(
                name="fixture_discovery_search",
                description="Fixture benchmark",
                max_seconds=1.0,
                average_seconds=0.75,
                median_seconds=0.75,
                min_seconds=0.70,
                max_observed_seconds=0.80,
                iterations_completed=25,
                regressed=False,
            ),
            benchmark_report.BenchmarkResult(
                name="query_variant_building",
                description="Query benchmark",
                max_seconds=0.20,
                average_seconds=0.25,
                median_seconds=0.24,
                min_seconds=0.21,
                max_observed_seconds=0.28,
                iterations_completed=25,
                regressed=True,
            ),
        ]

        markdown_report, text_report, json_payload = benchmark_report.build_report_artifacts(results)

        self.assertIn("fixture_discovery_search", markdown_report)
        self.assertIn("REGRESSION", markdown_report)
        self.assertIn("Benchmarks executed: 2", text_report)
        self.assertEqual(json_payload["summary"]["regressions_detected"], 1)

    def test_run_benchmark_report_writes_expected_artifacts_and_threshold_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline_path = root / "benchmarks.json"
            baseline_path.write_text(json.dumps({}), encoding="utf-8")
            results_dir = root / "results"
            case = benchmark_report.BenchmarkCase(
                name="fixture_discovery_search",
                description="Fixture benchmark",
                max_seconds=5.0,
                runner=lambda _project_root: 4,
            )

            with patch(
                "benchmark_report.time.perf_counter",
                side_effect=[0.0, 0.5],
            ):
                exit_code = benchmark_report.run_benchmark_report(
                    [
                        "--baseline-file",
                        str(baseline_path),
                        "--results-dir",
                        str(results_dir),
                        "--repeat",
                        "1",
                        "--iterations",
                        "1",
                        "--warmup",
                        "0",
                    ],
                    cases=[case],
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((results_dir / "benchmark_report.md").exists())
            self.assertTrue((results_dir / "benchmark_report.txt").exists())
            self.assertTrue((results_dir / "benchmark_summary.json").exists())
            self.assertTrue((results_dir / "benchmark_results.csv").exists())

            regressing_case = benchmark_report.BenchmarkCase(
                name="fixture_discovery_search",
                description="Fixture benchmark",
                max_seconds=0.10,
                runner=lambda _project_root: 4,
            )
            with patch(
                "benchmark_report.time.perf_counter",
                side_effect=[0.0, 0.5],
            ):
                regression_exit_code = benchmark_report.run_benchmark_report(
                    [
                        "--baseline-file",
                        str(baseline_path),
                        "--results-dir",
                        str(results_dir),
                        "--repeat",
                        "1",
                        "--iterations",
                        "1",
                        "--warmup",
                        "0",
                        "--fail-on-regression",
                    ],
                    cases=[regressing_case],
                )

            self.assertEqual(regression_exit_code, 2)

    def test_default_benchmark_helpers_use_project_fixtures(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        config = benchmark_report._build_temp_config(project_root)
        papers = benchmark_report._load_fixture_papers(project_root)

        self.assertTrue(config.fixture_data_path)
        self.assertGreaterEqual(len(papers), 1)
        self.assertGreater(benchmark_report._benchmark_fixture_discovery_search(project_root), 0)
        self.assertGreater(benchmark_report._benchmark_deduplicate_fixture_batch(project_root), 0)
        self.assertGreater(benchmark_report._benchmark_manual_import_csv_load(project_root), 0)
        self.assertGreater(benchmark_report._benchmark_query_variant_building(project_root), 0)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
