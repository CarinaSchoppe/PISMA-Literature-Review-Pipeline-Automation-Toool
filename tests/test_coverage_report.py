"""Tests for the standalone coverage report generator."""

from __future__ import annotations

import json
import sys
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
        self.assertIn("Overall result:", text_report)
        self.assertIn("Generated artifacts:", text_report)
        self.assertIn("Interpretation:", text_report)
        self.assertIn("Lowest-Coverage Files", text_report)
        self.assertEqual(json_summary["overall"]["percent_covered"], 95.0)
        self.assertEqual(json_summary["files"][0]["missing_ranges"], "10-11, 30")

    def test_build_arg_parser_supports_include_tests_and_custom_omit(self) -> None:
        parser = coverage_report.build_arg_parser()
        args = parser.parse_args(["--include-tests", "--omit", "foo/*", "--top-files", "7"])

        self.assertTrue(args.include_tests)
        self.assertEqual(args.omit, ["foo/*"])
        self.assertEqual(args.top_files, 7)

    def test_build_coverage_config_can_include_or_exclude_test_files(self) -> None:
        excluded = coverage_report._build_coverage_config(["tests/*", "build/*"])
        included = coverage_report._build_coverage_config([])

        self.assertIn("omit =", excluded)
        self.assertIn("tests/*", excluded)
        self.assertIn("build/*", excluded)
        self.assertNotIn("omit =", included)

    @patch("coverage_report._pytest_cov_is_available", return_value=True)
    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_writes_expected_artifacts(self, run_mock, _print_mock, _plugin_available) -> None:
        def fake_run(command, cwd=None, check=None, text=None, capture_output=False, env=None):
            self.assertIn("COVERAGE_FILE", env)
            self.assertIn("-m", command)
            self.assertIn("pytest", command)
            json_arg = next(part for part in command if part.startswith("--cov-report=json:"))
            html_arg = next(part for part in command if part.startswith("--cov-report=html:"))
            junit_arg = next(part for part in command if part.startswith("--junitxml="))
            output_path = Path(json_arg.split(":", 1)[1])
            html_path = Path(html_arg.split(":", 1)[1])
            junit_path = Path(junit_arg.split("=", 1)[1])
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
            html_path.mkdir(parents=True, exist_ok=True)
            (html_path / "index.html").write_text("<html></html>", encoding="utf-8")
            junit_path.write_text("<testsuite></testsuite>", encoding="utf-8")
            return type("Result", (), {"stdout": "============================= test session starts =============================\nTOTAL 90.00%\n"})()

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
            self.assertTrue((base / "junit.xml").exists())
            self.assertTrue((base / "pytest_terminal.txt").exists())
            self.assertFalse((base / ".coverage").exists())
            self.assertTrue((base / ".coveragerc").exists())
            self.assertIn("config.py", (base / "coverage_report.txt").read_text(encoding="utf-8"))

    @patch("coverage_report._pytest_cov_is_available", return_value=True)
    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_reports_when_no_threshold_was_requested(
        self,
        run_mock,
        print_mock,
        _plugin_available,
    ) -> None:
        def fake_run(command, cwd=None, check=None, text=None, capture_output=False, env=None):
            json_arg = next(part for part in command if part.startswith("--cov-report=json:"))
            html_arg = next(part for part in command if part.startswith("--cov-report=html:"))
            junit_arg = next(part for part in command if part.startswith("--junitxml="))
            Path(json_arg.split(":", 1)[1]).write_text(
                json.dumps(
                    {
                        "totals": {
                            "num_statements": 10,
                            "covered_lines": 10,
                            "missing_lines": 0,
                            "percent_covered": 100.0,
                        },
                        "files": {},
                    }
                ),
                encoding="utf-8",
            )
            html_path = Path(html_arg.split(":", 1)[1])
            html_path.mkdir(parents=True, exist_ok=True)
            (html_path / "index.html").write_text("<html></html>", encoding="utf-8")
            Path(junit_arg.split("=", 1)[1]).write_text("<testsuite></testsuite>", encoding="utf-8")
            return type("Result", (), {"stdout": "TOTAL 100.00%\n"})()

        run_mock.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(["--results-dir", tmpdir])

        self.assertEqual(exit_code, 0)
        printed_chunks = [" ".join(str(part) for part in call.args) for call in print_mock.call_args_list]
        self.assertTrue(
            any("Coverage threshold check: no fail-under threshold was requested for this run." in chunk for chunk in printed_chunks)
        )

    @patch("coverage_report._pytest_cov_is_available", return_value=True)
    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_can_fail_threshold(self, run_mock, _print_mock, _plugin_available) -> None:
        def fake_run(command, cwd=None, check=None, text=None, capture_output=False, env=None):
            self.assertIn("COVERAGE_FILE", env)
            json_arg = next(part for part in command if part.startswith("--cov-report=json:"))
            html_arg = next(part for part in command if part.startswith("--cov-report=html:"))
            junit_arg = next(part for part in command if part.startswith("--junitxml="))
            Path(json_arg.split(":", 1)[1]).write_text(
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
            html_path = Path(html_arg.split(":", 1)[1])
            html_path.mkdir(parents=True, exist_ok=True)
            (html_path / "index.html").write_text("<html></html>", encoding="utf-8")
            Path(junit_arg.split("=", 1)[1]).write_text("<testsuite></testsuite>", encoding="utf-8")
            return type("Result", (), {"stdout": "TOTAL 70.00%\n"})()

        run_mock.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(["--results-dir", tmpdir, "--fail-under", "95"])

        self.assertEqual(exit_code, 2)

    @patch("coverage_report._pytest_cov_is_available", return_value=True)
    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_handles_failed_pytest_before_artifacts_exist(
        self,
        run_mock,
        print_mock,
        _plugin_available,
    ) -> None:
        run_mock.return_value = type(
            "Result",
            (),
            {
                "stdout": "pytest failed early",
                "stderr": "traceback details",
                "returncode": 5,
            },
        )()

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(["--results-dir", tmpdir])

        self.assertEqual(exit_code, 5)
        printed_chunks = [" ".join(str(part) for part in call.args) for call in print_mock.call_args_list]
        self.assertTrue(any("Pytest execution transcript" in chunk for chunk in printed_chunks))
        self.assertTrue(any("Generated artifacts" in chunk for chunk in printed_chunks))
        self.assertTrue(any("pytest failed early" in chunk and "[stderr]" in chunk for chunk in printed_chunks))
        self.assertTrue(any("Pytest terminal log:" in chunk for chunk in printed_chunks))
        error_messages = [str(call.args[0]) for call in print_mock.call_args_list if call.kwargs.get("file") is sys.stderr]
        self.assertIn("Coverage report generation failed before coverage artifacts were written.", error_messages)

    @patch("coverage_report._pytest_cov_is_available", return_value=False)
    @patch("builtins.print")
    @patch("coverage_report.subprocess.run")
    def test_run_coverage_report_falls_back_to_coverage_py_when_pytest_cov_is_missing(
        self,
        run_mock,
        print_mock,
        _plugin_available,
    ) -> None:
        def fake_run(command, cwd=None, text=None, capture_output=False, env=None):
            if command[:4] == [sys.executable, "-m", "coverage", "run"]:
                junit_arg = next(part for part in command if part.startswith("--junitxml="))
                coverage_data_arg = next(part for part in command if part.startswith("--data-file="))
                Path(junit_arg.split("=", 1)[1]).write_text("<testsuite></testsuite>", encoding="utf-8")
                Path(coverage_data_arg.split("=", 1)[1]).write_text("coverage data", encoding="utf-8")
                return type("Result", (), {"stdout": "fallback pytest run", "stderr": "", "returncode": 0})()
            if command[:4] == [sys.executable, "-m", "coverage", "json"]:
                raw_json_path = Path(command[command.index("-o") + 1])
                raw_json_path.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "num_statements": 10,
                                "covered_lines": 10,
                                "missing_lines": 0,
                                "percent_covered": 100.0,
                            },
                            "files": {},
                        }
                    ),
                    encoding="utf-8",
                )
                return type("Result", (), {"stdout": "coverage json ok", "stderr": "", "returncode": 0})()
            if command[:4] == [sys.executable, "-m", "coverage", "html"]:
                html_dir = Path(command[command.index("-d") + 1])
                html_dir.mkdir(parents=True, exist_ok=True)
                (html_dir / "index.html").write_text("<html></html>", encoding="utf-8")
                return type("Result", (), {"stdout": "coverage html ok", "stderr": "", "returncode": 0})()
            raise AssertionError(f"Unexpected command: {command}")

        run_mock.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = coverage_report.run_coverage_report(["--results-dir", tmpdir, "--fail-under", "99.5"])

        self.assertEqual(exit_code, 0)
        printed_chunks = [" ".join(str(part) for part in call.args) for call in print_mock.call_args_list]
        self.assertTrue(any("coverage.py fallback runner" in chunk for chunk in printed_chunks))

    @patch("coverage_report.run_coverage_report", return_value=0)
    def test_main_exits_with_report_status(self, run_mock) -> None:
        with self.assertRaises(SystemExit) as caught:
            coverage_report.main()

        self.assertEqual(caught.exception.code, 0)
        run_mock.assert_called_once()


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
