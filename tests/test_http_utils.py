"""Tests for HTTP helpers such as throttling, request wrappers, and log sanitization."""

from __future__ import annotations

import tempfile
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
        self.temp_dir = tempfile.TemporaryDirectory()
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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

    def test_rate_limiter_wait_returns_immediately_when_interval_is_disabled(self) -> None:
        limiter = http.RateLimiter(calls_per_second=0.0)

        with patch("utils.http.time.sleep") as sleep_mock:
            limiter.wait()

        sleep_mock.assert_not_called()

    def test_build_session_applies_headers_and_retries(self) -> None:
        session = http.build_session("Agent/1.0", extra_headers={"X-Test": "yes"})

        self.assertEqual(session.headers["User-Agent"], "Agent/1.0")
        self.assertEqual(session.headers["Accept"], "application/json")
        self.assertEqual(session.headers["X-Test"], "yes")

    def test_configure_http_runtime_updates_cache_and_retry_settings(self) -> None:
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=120,
            retry_max_attempts=7,
            retry_base_delay_seconds=2.5,
            retry_max_delay_seconds=12.0,
        )

        self.assertTrue(http.HTTP_RUNTIME_CONFIG.cache_enabled)
        self.assertEqual(http.HTTP_RUNTIME_CONFIG.cache_ttl_seconds, 120)
        self.assertEqual(http.HTTP_RUNTIME_CONFIG.retry_max_attempts, 7)
        self.assertEqual(http.HTTP_RUNTIME_CONFIG.retry_base_delay_seconds, 2.5)
        self.assertEqual(http.HTTP_RUNTIME_CONFIG.retry_max_delay_seconds, 12.0)

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

    def test_request_helpers_return_none_when_backoff_returns_none(self) -> None:
        session = Mock()

        with patch("utils.http._request_with_backoff", return_value=None):
            self.assertIsNone(http.request_json(session, "GET", "https://example.org/api"))
            self.assertIsNone(http.request_content(session, "https://example.org/file.pdf"))
            self.assertIsNone(http.request_text(session, "GET", "https://example.org/feed.txt"))

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

    def test_request_json_uses_persistent_cache_for_get_requests(self) -> None:
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )
        session = Mock()
        session.request.return_value = FakeResponse(payload={"cached": True})

        first = http.request_json(session, "GET", "https://example.org/api", params={"q": "llm"})
        second = http.request_json(session, "GET", "https://example.org/api", params={"q": "llm"})

        self.assertEqual(first, {"cached": True})
        self.assertEqual(second, {"cached": True})
        session.request.assert_called_once()

    def test_request_text_uses_persistent_cache_for_get_requests(self) -> None:
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )
        session = Mock()
        session.request.return_value = FakeResponse(text="cached text", content=b"x")

        first = http.request_text(session, "GET", "https://example.org/feed.txt", params={"q": "llm"})
        second = http.request_text(session, "GET", "https://example.org/feed.txt", params={"q": "llm"})

        self.assertEqual(first, "cached text")
        self.assertEqual(second, "cached text")
        session.request.assert_called_once()

    def test_persistent_cache_load_handles_corrupt_files_kind_mismatches_and_explicit_cache_flags(self) -> None:
        cache = http.PersistentResponseCache(http.Path(self.temp_dir.name), ttl_seconds=60)
        cache_path = http.Path(self.temp_dir.name) / "bad.json"
        cache_path.write_text("{not-json", encoding="utf-8")

        self.assertIsNone(cache.load("bad", expected_kind="json"))

        cache.store("kind-mismatch", kind="text", payload="hello")
        self.assertIsNone(cache.load("kind-mismatch", expected_kind="json"))
        self.assertTrue(http._should_use_cache("POST", True))
        self.assertFalse(http._should_use_cache("GET", False))

    def test_persistent_cache_load_handles_read_errors(self) -> None:
        cache = http.PersistentResponseCache(http.Path(self.temp_dir.name), ttl_seconds=60)
        cache_path = http.Path(self.temp_dir.name) / "bad.json"
        cache_path.write_text("{}", encoding="utf-8")

        with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
            self.assertIsNone(cache.load("bad", expected_kind="json"))

    def test_cached_payload_is_ignored_after_ttl_expiry(self) -> None:
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=1,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )
        session = Mock()
        session.request.return_value = FakeResponse(payload={"fresh": True})

        with patch("utils.http.time.time", side_effect=[100.0, 102.5, 102.5]):
            first = http.request_json(session, "GET", "https://example.org/api", params={"page": 1})
            second = http.request_json(session, "GET", "https://example.org/api", params={"page": 1})

        self.assertEqual(first, {"fresh": True})
        self.assertEqual(second, {"fresh": True})
        self.assertEqual(session.request.call_count, 2)

    def test_request_json_does_not_cache_post_requests_by_default(self) -> None:
        http.configure_http_runtime(
            cache_enabled=True,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )
        session = Mock()
        session.request.return_value = FakeResponse(payload={"ok": True})

        http.request_json(session, "POST", "https://example.org/api", json={"prompt": "hello"})
        http.request_json(session, "POST", "https://example.org/api", json={"prompt": "hello"})

        self.assertEqual(session.request.call_count, 2)

    def test_request_json_retries_on_429_with_retry_after_header(self) -> None:
        session = Mock()
        session.request.side_effect = [
            FakeResponse(status_code=429, headers={"Retry-After": "3"}),
            FakeResponse(payload={"ok": True}),
        ]

        with patch("utils.http.time.sleep") as sleep_mock:
            payload = http.request_json(session, "GET", "https://example.org/api")

        self.assertEqual(payload, {"ok": True})
        sleep_mock.assert_called_once_with(3.0)
        self.assertEqual(session.request.call_count, 2)

    def test_request_json_retries_on_429_with_exponential_backoff(self) -> None:
        session = Mock()
        session.request.side_effect = [
            FakeResponse(status_code=429),
            FakeResponse(payload={"ok": True}),
        ]
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=2.0,
            retry_max_delay_seconds=30.0,
        )

        with patch("utils.http.time.sleep") as sleep_mock:
            payload = http.request_json(session, "GET", "https://example.org/api")

        self.assertEqual(payload, {"ok": True})
        sleep_mock.assert_called_once_with(2.0)

    def test_request_json_returns_none_after_final_429_failure(self) -> None:
        session = Mock()
        session.request.side_effect = [
            FakeResponse(status_code=429),
            FakeResponse(
                status_code=429,
                raise_error=requests.HTTPError("still rate limited"),
            ),
        ]
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=2,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )

        with patch("utils.http.time.sleep"):
            payload = http.request_json(session, "GET", "https://example.org/api")

        self.assertIsNone(payload)

    def test_request_json_can_return_none_when_final_429_response_does_not_raise(self) -> None:
        session = Mock()
        session.request.return_value = FakeResponse(status_code=429)
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=1,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=30.0,
        )

        payload = http.request_json(session, "GET", "https://example.org/api")

        self.assertIsNone(payload)

    def test_request_content_handles_success_and_failure(self) -> None:
        success_session = Mock()
        success_session.request.return_value = FakeResponse(content=b"%PDF", headers={"Content-Type": "application/pdf"})
        failure_session = Mock()
        failure_session.request.side_effect = requests.RequestException("download failed")

        self.assertIsNotNone(http.request_content(success_session, "https://example.org/file.pdf"))
        self.assertIsNone(http.request_content(failure_session, "https://example.org/file.pdf"))

    def test_request_text_handles_success_and_failure(self) -> None:
        success_session = Mock()
        success_session.request.return_value = FakeResponse(text="<xml>ok</xml>", content=b"x")
        failure_session = Mock()
        failure_session.request.side_effect = requests.RequestException("boom")

        self.assertEqual(http.request_text(success_session, "GET", "https://example.org/text"), "<xml>ok</xml>")
        self.assertIsNone(http.request_text(failure_session, "GET", "https://example.org/text"))

    def test_calculate_backoff_delay_clamps_large_retry_after_values(self) -> None:
        response = FakeResponse(status_code=429, headers={"Retry-After": "999"})
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=1.0,
            retry_max_delay_seconds=5.0,
        )

        delay = http._calculate_backoff_delay(response, 1)

        self.assertEqual(delay, 5.0)

    def test_calculate_backoff_delay_falls_back_when_retry_after_is_invalid(self) -> None:
        response = FakeResponse(status_code=429, headers={"Retry-After": "not-a-number"})
        http.configure_http_runtime(
            cache_enabled=False,
            cache_dir=self.temp_dir.name,
            cache_ttl_seconds=3600,
            retry_max_attempts=4,
            retry_base_delay_seconds=0.0,
            retry_max_delay_seconds=5.0,
        )

        delay = http._calculate_backoff_delay(response, 1)

        self.assertEqual(delay, 0.0)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
