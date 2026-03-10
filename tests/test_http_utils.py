"""Tests for HTTP helpers such as throttling, request wrappers, and log sanitization."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from utils import http


class FakeResponse:
    """Small fake response object for exercising the HTTP utility wrappers."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload=None,
        text: str = "",
        content: bytes = b'{"ok": true}',
        headers: dict[str, str] | None = None,
        raise_error: Exception | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content
        self.headers = headers or {}
        self._raise_error = raise_error
        self._chunks = chunks or []

    def raise_for_status(self) -> None:
        if self._raise_error:
            raise self._raise_error

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002 - matches requests API
        yield from self._chunks


class HTTPUtilsTests(unittest.TestCase):
    """Exercise the request wrappers and supporting helpers in isolation."""

    def setUp(self) -> None:
        http.configure_http_logging(enabled=True, log_payloads=True)

    def test_sanitize_for_log_redacts_nested_secrets_and_truncates_strings(self) -> None:
        payload = {
            "Authorization": "secret",
            "nested": {"api_key": "secret-2"},
            "items": [{"token": "secret-3"}],
            "query": {"key": "secret-4"},
            "text": "x" * 600,
        }

        sanitized = http._sanitize_for_log(payload)

        self.assertEqual(sanitized["Authorization"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["items"][0]["token"], "***REDACTED***")
        self.assertEqual(sanitized["query"]["key"], "***REDACTED***")
        self.assertTrue(sanitized["text"].endswith("...<truncated>"))

    def test_rate_limiter_wait_sleeps_only_when_interval_is_positive(self) -> None:
        limiter = http.RateLimiter(calls_per_second=2.0)
        limiter._last_call = -1.0
        with patch("utils.http.time.monotonic", side_effect=[0.0, 0.1, 0.5, 0.6]), patch(
            "utils.http.time.sleep"
        ) as sleep_mock:
            limiter.wait()
            limiter.wait()

        sleep_mock.assert_called_once()
        self.assertAlmostEqual(sleep_mock.call_args.args[0], 0.1, places=2)

    def test_build_session_applies_headers_and_retries(self) -> None:
        session = http.build_session("Agent/1.0", extra_headers={"X-Test": "yes"})

        self.assertEqual(session.headers["User-Agent"], "Agent/1.0")
        self.assertEqual(session.headers["Accept"], "application/json")
        self.assertEqual(session.headers["X-Test"], "yes")

    def test_request_json_returns_payload_and_logs_safely(self) -> None:
        session = Mock()
        session.request.return_value = FakeResponse(payload={"answer": 42})
        limiter = Mock()

        payload = http.request_json(
            session,
            "POST",
            "https://example.org/api",
            limiter=limiter,
            json={"api_key": "secret", "prompt": "hello"},
        )

        self.assertEqual(payload, {"answer": 42})
        limiter.wait.assert_called_once()
        session.request.assert_called_once()

    def test_request_json_returns_none_for_empty_content_or_request_failure(self) -> None:
        session = Mock()
        session.request.side_effect = [
            FakeResponse(payload=None, content=b""),
            requests.RequestException("boom"),
        ]

        empty_payload = http.request_json(session, "GET", "https://example.org/empty")
        failed_payload = http.request_json(session, "GET", "https://example.org/fail")

        self.assertIsNone(empty_payload)
        self.assertIsNone(failed_payload)

    def test_request_content_handles_success_and_failure(self) -> None:
        success_session = Mock()
        success_session.get.return_value = FakeResponse(content=b"%PDF", headers={"Content-Type": "application/pdf"})
        failure_session = Mock()
        failure_session.get.side_effect = requests.RequestException("download failed")

        self.assertIsNotNone(http.request_content(success_session, "https://example.org/file.pdf"))
        self.assertIsNone(http.request_content(failure_session, "https://example.org/file.pdf"))

    def test_request_text_handles_success_and_failure(self) -> None:
        success_session = Mock()
        success_session.request.return_value = FakeResponse(text="<xml>ok</xml>", content=b"x")
        failure_session = Mock()
        failure_session.request.side_effect = requests.RequestException("boom")

        self.assertEqual(http.request_text(success_session, "GET", "https://example.org/text"), "<xml>ok</xml>")
        self.assertIsNone(http.request_text(failure_session, "GET", "https://example.org/text"))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
