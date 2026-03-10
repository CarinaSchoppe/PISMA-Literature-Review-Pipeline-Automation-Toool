from __future__ import annotations

import unittest

from config import build_arg_parser
from ui.launcher import LaunchMode, has_explicit_run_arguments, prompt_for_launch_mode


class LauncherTests(unittest.TestCase):
    def test_has_explicit_run_arguments_ignores_ui_switch(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--ui"])

        self.assertFalse(has_explicit_run_arguments(args, ["--ui"]))

    def test_has_explicit_run_arguments_detects_regular_flags(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--topic", "LLMs"])

        self.assertTrue(has_explicit_run_arguments(args, ["--topic", "LLMs"]))

    def test_prompt_for_launch_mode_accepts_menu_choices(self) -> None:
        mode = prompt_for_launch_mode(input_fn=lambda _prompt: "2", print_fn=lambda _message: None)

        self.assertEqual(mode, LaunchMode.CLASSIC_WIZARD)
