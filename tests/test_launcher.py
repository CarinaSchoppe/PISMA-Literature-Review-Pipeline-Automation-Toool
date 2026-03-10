"""Tests for the startup launcher that chooses UI, wizard, or headless execution."""

from __future__ import annotations

import unittest

from config import build_arg_parser
from ui.launcher import LaunchMode, has_explicit_run_arguments, prompt_for_launch_mode


class LauncherTests(unittest.TestCase):
    """Verify launcher mode detection and menu handling."""

    def test_has_explicit_run_arguments_ignores_ui_switch(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--ui"])

        self.assertFalse(has_explicit_run_arguments(args, ["--ui"]))

    def test_has_explicit_run_arguments_detects_regular_flags(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--topic", "LLMs"])

        self.assertTrue(has_explicit_run_arguments(args, ["--topic", "LLMs"]))

    def test_has_explicit_run_arguments_can_inspect_namespace_without_argv(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--topic", "LLMs"])

        self.assertTrue(has_explicit_run_arguments(args))

    def test_has_explicit_run_arguments_returns_false_for_empty_namespace(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])

        self.assertFalse(has_explicit_run_arguments(args))

    def test_prompt_for_launch_mode_accepts_menu_choices(self) -> None:
        mode = prompt_for_launch_mode(input_fn=lambda _prompt: "2", print_fn=lambda _message: None)

        self.assertEqual(mode, LaunchMode.CLASSIC_WIZARD)

    def test_prompt_for_launch_mode_reprompts_on_invalid_input_and_supports_defaults(self) -> None:
        printed: list[str] = []
        answers = iter(["9", "", "3"])

        guided = prompt_for_launch_mode(input_fn=lambda _prompt: next(answers), print_fn=printed.append)

        self.assertEqual(guided, LaunchMode.GUIDED_DESKTOP)
        self.assertIn("Please enter 1, 2, or 3.", printed)

        quit_mode = prompt_for_launch_mode(input_fn=lambda _prompt: "3", print_fn=lambda _message: None)
        self.assertEqual(quit_mode, LaunchMode.QUIT)
