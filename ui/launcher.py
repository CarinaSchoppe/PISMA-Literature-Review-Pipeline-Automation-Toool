"""Console startup helpers that route users into the desktop UI or classic wizard."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Sequence


class LaunchMode(str, Enum):
    """Supported startup modes for the main entrypoint."""

    GUIDED_DESKTOP = "guided_desktop"
    CLASSIC_WIZARD = "classic_wizard"
    QUIT = "quit"


def has_explicit_run_arguments(args: Any, argv: Sequence[str] | None = None) -> bool:
    """Return True when parsed CLI arguments describe a direct headless run."""

    if argv is not None:
        return any(argument not in {"--ui", "--wizard"} for argument in argv)
    ignored = {"ui", "wizard"}
    for key, value in vars(args).items():
        if key in ignored:
            continue
        if value is None or value is False:
            continue
        if isinstance(value, list) and not value:
            continue
        return True
    return False


def prompt_for_launch_mode(
        *,
        input_fn: Callable[[str], str] = input,
        print_fn: Callable[[str], None] = print,
) -> LaunchMode:
    """Ask the user which startup experience to open."""

    prompt = (
        "\nSelect startup mode:\n"
        "  1. Guided desktop UI\n"
        "  2. Classic console wizard\n"
        "  3. Quit\n"
    )
    while True:
        print_fn(prompt)
        choice = input_fn("Enter choice [1-3]: ").strip()
        if choice in {"1", ""}:
            return LaunchMode.GUIDED_DESKTOP
        if choice == "2":
            return LaunchMode.CLASSIC_WIZARD
        if choice == "3":
            return LaunchMode.QUIT
        print_fn("Please enter 1, 2, or 3.")
