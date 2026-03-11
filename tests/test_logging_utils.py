"""Tests for shared logging helpers and verbosity normalization."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from utils import logging_utils


class _MemoryHandler(logging.Handler):
    """Minimal handler used to verify extra handler wiring without side effects."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial test helper
        return None


class _BrokenCloseHandler(logging.Handler):
    """Handler that raises during close so cleanup branches stay tested."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial test helper
        return None

    def close(self) -> None:
        raise RuntimeError("close failed")


class LoggingUtilsTests(unittest.TestCase):
    """Exercise TRACE registration, verbosity aliases, and file-backed logging setup."""

    def setUp(self) -> None:
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.original_level = self.root_logger.level

    def tearDown(self) -> None:
        for handler in list(self.root_logger.handlers):
            self.root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        for handler in self.original_handlers:
            self.root_logger.addHandler(handler)
        self.root_logger.setLevel(self.original_level)

    def test_normalize_verbosity_accepts_aliases(self) -> None:
        self.assertEqual(logging_utils.normalize_verbosity("important only"), "normal")
        self.assertEqual(logging_utils.normalize_verbosity("quiet"), "normal")
        self.assertEqual(logging_utils.normalize_verbosity("verbose"), "verbose")
        self.assertEqual(logging_utils.normalize_verbosity("ultra-verbose"), "ultra_verbose")
        self.assertEqual(logging_utils.normalize_verbosity("debug"), "ultra_verbose")

    def test_verbosity_to_logging_level_maps_trace_mode(self) -> None:
        self.assertEqual(logging_utils.verbosity_to_logging_level("normal"), logging.INFO)
        self.assertEqual(logging_utils.verbosity_to_logging_level("verbose"), logging.DEBUG)
        self.assertEqual(logging_utils.verbosity_to_logging_level("ultra_verbose"), logging_utils.TRACE_LEVEL)

    def test_install_trace_level_is_idempotent_when_trace_method_already_exists(self) -> None:
        original_trace = getattr(logging.Logger, "trace", None)
        self.assertIsNotNone(original_trace)
        logging_utils._install_trace_level()
        self.assertIs(getattr(logging.Logger, "trace", None), original_trace)

    def test_build_log_file_path_defaults_into_results_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resolved = logging_utils.build_log_file_path(results_dir=temp_dir)
            self.assertEqual(resolved, Path(temp_dir) / "pipeline.log")
            self.assertTrue(resolved.parent.exists())

    def test_configure_application_logging_writes_to_file_and_supports_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "custom.log"
            extra_handler = _MemoryHandler()

            resolved = logging_utils.configure_application_logging(
                "ultra_verbose",
                log_file_path=log_path,
                extra_handlers=[extra_handler],
            )
            try:
                logger = logging.getLogger("tests.logging_utils")
                logger.log(logging_utils.TRACE_LEVEL, "trace message")
                logger.info("info message")
            finally:
                for handler in list(logging.getLogger().handlers):
                    handler.flush()

            self.assertEqual(resolved, log_path)
            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("TRACE", contents)
            self.assertIn("trace message", contents)
            self.assertIn("info message", contents)
            self.root_logger.addHandler(_BrokenCloseHandler())
            for handler in list(self.root_logger.handlers):
                self.root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    def test_logger_trace_method_writes_when_trace_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "trace.log"
            logging_utils.configure_application_logging("ultra_verbose", log_file_path=log_path)
            logger = logging.getLogger("tests.logging_utils.trace_method")
            cast_trace = getattr(logger, "trace")
            cast_trace("trace via method")
            for handler in list(logging.getLogger().handlers):
                handler.flush()

            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("trace via method", contents)
            self.root_logger.addHandler(_BrokenCloseHandler())
            for handler in list(self.root_logger.handlers):
                self.root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    def test_configure_application_logging_ignores_handler_close_failures(self) -> None:
        self.root_logger.addHandler(_BrokenCloseHandler())
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "safe.log"
            resolved = logging_utils.configure_application_logging("normal", log_file_path=log_path)
            self.assertEqual(resolved, log_path)
            self.assertTrue(log_path.exists())
            self.root_logger.addHandler(_BrokenCloseHandler())
            for handler in list(self.root_logger.handlers):
                self.root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    def test_teardown_tolerates_broken_handler_close(self) -> None:
        self.root_logger.addHandler(_BrokenCloseHandler())


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
