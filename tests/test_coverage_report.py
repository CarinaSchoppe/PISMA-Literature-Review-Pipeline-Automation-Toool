"""Tests for the standalone coverage report generator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import coverage_report


class CoverageReportTests(unittest.TestCase):
    """Exercise the JaCoCo-style coverage report helper without rerunning the real suite."""

    def test_compress_line_ranges_formats_empty_single_and_multiple_ranges(self) -> None:
        self.assertEqual(coverage_report.compress_line_ranges([]), "-")
        self.assertEqual(coverage_report.compress_line_ranges([5]), "5")
        self.assertEqual(coverage_report.compress_line_ranges([1, 2, 3, 5, 7, 8]), "1-3, 5, 7-8")

    def test_summarize_coverage_payload_sorts_lowest_coverage_first(self) -> None:
        payload = {
            "totals": {
                "num_statements": 20,
                "covered_lines": 16,
                "missing_lines": 4,
                "percent_covered": 80.0,
            },
            "files": {
                "b.py": {
                    "summary": {"num_statements": 10, "covered_lines": 10, "percent_covered": 100.0},
                    "missing_lines": [],
                },
                "a.py": {
                    "summary": {"num_statements": 10, "covered_lines": 6, "percent_covered": 60.0},
                    "missing_lines": [4, 5, 6, 9],
                },
            },
        }

        summary = coverage_report.summarize_coverage_payload(payload)

        self.assertEqual(summary.total_statements, 20)
        self.assertEqual(summary.files[0].path, "a.py")
        self.assertEqual(summary.files[0].missing_ranges, "4-6, 9")
        self.assertEqual(summary.files[1].path, "b.py")

    def test_build_report_artifacts_renders_markdown_text_and_json(self) -> None:
        summary = coverage_report.CoverageSummary(
            total_statements=100,
            covered_lines=95,
            missing_lines=5,
            percent_covered=95.0,
            files=[
                coverage_report.CoverageFileSummary(
                    path="config.py",
                    statements=50,
                    covered_lines=45,
                    missing_lines=[10, 11, 30],
                    percent_covered=90.0,
                )
            ],
        )

        markdown, text_report, json_summary = coverage_report.build_report_artifacts(
            summary,
            top_files=5,
            html_index_path=Path("results/coverage/html/index.html"),
            raw_json_path=Path("results/coverage/coverage.json"),
        )

        self.assertIn("Overall coverage: `95.00%`", markdown)
        self.assertIn("config.py", markdown)
        self.assertIn("10-11, 30", markdown)
        self.assertIn("Lowest-Coverage Files", text_report)
        self.assertEqual(json_summary["overall"]["percent_covered"], 95.0)
        self.assertEqual(json_summary["files"][0]["missing_ranges"], "10-11, 30")

    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_writes_expected_artifacts(self, run_mock, _print_mock) -> None:
        def fake_run(command, cwd=None, check=None, text=None, capture_output=False):
            if "json" in command:
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "num_statements": 10,
                                "covered_lines": 9,
                                "missing_lines": 1,
                                "percent_covered": 90.0,
                            },
                            "files": {
                                "config.py": {
                                    "summary": {
                                        "num_statements": 10,
                                        "covered_lines": 9,
                                        "percent_covered": 90.0,
                                    },
                                    "missing_lines": [42],
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            if "report" in command:
                return type("Result", (), {"stdout": "TOTAL 90.00%\n"})()
            return type("Result", (), {"stdout": ""})()

        run_mock.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(
                ["--results-dir", tmpdir, "--top-files", "3", "--fail-under", "80"]
            )

            self.assertEqual(exit_code, 0)
            base = (Path(coverage_report.__file__).resolve().parent / tmpdir).resolve()
            self.assertTrue((base / "coverage.json").exists())
            self.assertTrue((base / "coverage_report.md").exists())
            self.assertTrue((base / "coverage_report.txt").exists())
            self.assertTrue((base / "coverage_summary.json").exists())
            self.assertIn("config.py", (base / "coverage_report.txt").read_text(encoding="utf-8"))

    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_can_fail_threshold(self, run_mock, _print_mock) -> None:
        def fake_run(command, cwd=None, check=None, text=None, capture_output=False):
            if "json" in command:
                output_path = Path(command[command.index("-o") + 1])
                output_path.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "num_statements": 10,
                                "covered_lines": 7,
                                "missing_lines": 3,
                                "percent_covered": 70.0,
                            },
                            "files": {},
                        }
                    ),
                    encoding="utf-8",
                )
            if "report" in command:
                return type("Result", (), {"stdout": "TOTAL 70.00%\n"})()
            return type("Result", (), {"stdout": ""})()

        run_mock.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(["--results-dir", tmpdir, "--fail-under", "95"])

        self.assertEqual(exit_code, 2)

    def test_build_arg_parser_supports_include_tests_and_custom_omit(self) -> None:
        parser = coverage_report.build_arg_parser()
        args = parser.parse_args(["--include-tests", "--omit", "foo/*", "--top-files", "7"])

        self.assertTrue(args.include_tests)
        self.assertEqual(args.omit, ["foo/*"])
        self.assertEqual(args.top_files, 7)
