"""Tests for the top-level application entrypoint and startup routing."""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import main
from config import ResearchConfig
from ui.launcher import LaunchMode


class MainEntrypointTests(unittest.TestCase):
    """Exercise startup routing, headless execution, and logging configuration."""

    def test_configure_logging_maps_known_levels(self) -> None:
        with patch("main.logging.basicConfig") as basic_config:
            main.configure_logging("ultra_verbose")
            basic_config.assert_called_once()
            self.assertEqual(basic_config.call_args.kwargs["level"], 5)

    def test_run_headless_executes_pipeline_and_prints_outputs(self) -> None:
        config = ResearchConfig(
            research_topic="Large language models",
            search_keywords=["survey"],
            disable_progress_bars=True,
        ).finalize()
        result = {
            "discovered_count": 5,
            "deduplicated_count": 4,
            "database_count": 4,
            "papers_csv": "results/papers.csv",
            "review_summary_md": "results/review_summary.md",
        }
        controller_instance = Mock()
        controller_instance.run.return_value = result

        with (
            patch("main.ResearchConfig.from_cli", return_value=config),
            patch("main.configure_logging") as configure_logging,
            patch("main.configure_http_logging") as configure_http_logging,
            patch("main.PipelineController", return_value=controller_instance),
            io.StringIO() as buffer,
            redirect_stdout(buffer),
        ):
            exit_code = main._run_headless(argparse.Namespace())
            output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        configure_logging.assert_called_once_with(config.verbosity, log_file_path=str(config.log_file_path))
        configure_http_logging.assert_called_once_with(
            enabled=config.log_http_requests,
            log_payloads=config.log_http_payloads,
        )
        self.assertIn("Pipeline completed.", output)
        self.assertIn("Persistent log file:", output)
        self.assertIn("CSV summary: results/papers.csv", output)
        self.assertIn("Review summary: results/review_summary.md", output)

    def test_main_routes_directly_to_ui_when_ui_flag_is_set(self) -> None:
        args = argparse.Namespace(ui=True, wizard=False)

        with (
            patch("main.build_arg_parser") as build_arg_parser,
            patch("ui.desktop_app.launch_desktop_app", return_value=7) as launch_desktop_app,
        ):
            build_arg_parser.return_value.parse_args.return_value = args
            exit_code = main.main()

        self.assertEqual(exit_code, 7)
        launch_desktop_app.assert_called_once_with(args)

    def test_main_routes_headless_when_wizard_or_explicit_args_are_present(self) -> None:
        for args in (
            argparse.Namespace(ui=False, wizard=True),
            argparse.Namespace(ui=False, wizard=False),
        ):
            with self.subTest(args=args):
                with (
                    patch("main.build_arg_parser") as build_arg_parser,
                    patch("main.has_explicit_run_arguments", return_value=not args.wizard),
                    patch("main._run_headless", return_value=3) as run_headless,
                ):
                    build_arg_parser.return_value.parse_args.return_value = args
                    exit_code = main.main()

                self.assertEqual(exit_code, 3)
                run_headless.assert_called_once_with(args)

    def test_main_routes_from_launcher_menu(self) -> None:
        args = argparse.Namespace(ui=False, wizard=False)

        with (
            patch("main.build_arg_parser") as build_arg_parser,
            patch("main.has_explicit_run_arguments", return_value=False),
            patch("main.prompt_for_launch_mode", return_value=LaunchMode.GUIDED_DESKTOP),
            patch("ui.desktop_app.launch_desktop_app", return_value=5) as launch_desktop_app,
        ):
            build_arg_parser.return_value.parse_args.return_value = args
            exit_code = main.main()

        self.assertEqual(exit_code, 5)
        launch_desktop_app.assert_called_once_with(args)

        with (
            patch("main.build_arg_parser") as build_arg_parser,
            patch("main.has_explicit_run_arguments", return_value=False),
            patch("main.prompt_for_launch_mode", return_value=LaunchMode.CLASSIC_WIZARD),
            patch("main._run_headless", return_value=2) as run_headless,
        ):
            build_arg_parser.return_value.parse_args.return_value = args
            exit_code = main.main()

        self.assertEqual(exit_code, 2)
        run_headless.assert_called_once_with(args)

        with (
            patch("main.build_arg_parser") as build_arg_parser,
            patch("main.has_explicit_run_arguments", return_value=False),
            patch("main.prompt_for_launch_mode", return_value=LaunchMode.QUIT),
        ):
            build_arg_parser.return_value.parse_args.return_value = args
            exit_code = main.main()

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
