"""Shared logging helpers for CLI, GUI, file logging, and custom TRACE support."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

TRACE_LEVEL = 5
TRACE_NAME = "TRACE"


def _install_trace_level() -> None:
    """Register a TRACE level and logger method once per process."""

    if logging.getLevelName(TRACE_LEVEL) != TRACE_NAME:
        logging.addLevelName(TRACE_LEVEL, TRACE_NAME)

    if hasattr(logging.Logger, "trace"):
        return

    def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
        """Log one message at TRACE level when the logger is enabled for it."""

        if self.isEnabledFor(TRACE_LEVEL):
            self._log(TRACE_LEVEL, message, args, **kwargs)

    setattr(logging.Logger, "trace", trace)


_install_trace_level()

VERBOSITY_ALIASES = {
    "important only": "normal",
    "important_only": "normal",
    "normal": "normal",
    "quiet": "normal",
    "verbose": "verbose",
    "ultra verbose": "ultra_verbose",
    "ultra-verbose": "ultra_verbose",
    "ultra_verbose": "ultra_verbose",
    "debug": "ultra_verbose",
}

VERBOSITY_LEVEL_MAP = {
    "normal": logging.INFO,
    "verbose": logging.DEBUG,
    "ultra_verbose": TRACE_LEVEL,
}

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def normalize_verbosity(value: str | None) -> str:
    """Normalize old aliases and UI labels into the canonical verbosity names."""

    normalized = str(value or "normal").strip().lower()
    return VERBOSITY_ALIASES.get(normalized, normalized)


def verbosity_to_logging_level(value: str | None) -> int:
    """Convert one supported verbosity label into the concrete logging level."""

    return VERBOSITY_LEVEL_MAP.get(normalize_verbosity(value), logging.INFO)


def build_log_file_path(*, results_dir: str | Path, explicit_path: str | Path | None = None) -> Path:
    """Resolve the persistent log file path for one run."""

    if explicit_path is not None and explicit_path != "":
        path = Path(explicit_path)
    else:
        path = Path(results_dir) / "pipeline.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def configure_application_logging(
        verbosity: str,
        *,
        log_file_path: str | Path,
        extra_handlers: list[logging.Handler] | None = None,
) -> Path:
    """Configure root logging for console, GUI mirroring, and persistent file output."""

    level = verbosity_to_logging_level(verbosity)
    resolved_log_path = build_log_file_path(results_dir=Path(log_file_path).parent, explicit_path=log_file_path)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(resolved_log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stream_handler, file_handler]
    for handler in extra_handlers or []:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handlers.append(handler)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)
    return resolved_log_path
