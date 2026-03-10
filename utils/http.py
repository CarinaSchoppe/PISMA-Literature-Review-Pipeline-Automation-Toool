from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
HTTP_LOG_ENABLED = True
HTTP_LOG_PAYLOADS = True


def configure_http_logging(*, enabled: bool, log_payloads: bool) -> None:
    """Configure HTTP request logging for the current process."""

    global HTTP_LOG_ENABLED, HTTP_LOG_PAYLOADS
    HTTP_LOG_ENABLED = enabled
    HTTP_LOG_PAYLOADS = log_payloads


def _sanitize_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(token in normalized_key for token in ("authorization", "api_key", "apikey", "token")):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = _sanitize_for_log(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_log(item) for item in value]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "...<truncated>"
    return value


class RateLimiter:
    def __init__(self, calls_per_second: float = 1.0) -> None:
        self.min_interval = 1.0 / calls_per_second if calls_per_second > 0 else 0.0
        self._lock = Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


def build_session(user_agent: str, extra_headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    timeout: int = 30,
    **kwargs: Any,
) -> Any:
    if limiter:
        limiter.wait()
    if HTTP_LOG_ENABLED:
        LOGGER.info(
            "HTTP %s %s params=%s",
            method,
            url,
            _sanitize_for_log(kwargs.get("params")),
        )
        if HTTP_LOG_PAYLOADS and "json" in kwargs:
            LOGGER.debug("HTTP %s payload=%s", url, _sanitize_for_log(kwargs.get("json")))
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        if HTTP_LOG_ENABLED:
            LOGGER.info("HTTP %s %s -> %s", method, url, response.status_code)
        if not response.content:
            return None
        payload = response.json()
        if HTTP_LOG_PAYLOADS:
            LOGGER.debug("HTTP %s response=%s", url, _sanitize_for_log(payload))
        return payload
    except requests.RequestException as exc:
        LOGGER.warning("Request failed for %s: %s", url, exc)
        return None


def request_content(
    session: requests.Session,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    timeout: int = 60,
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response | None:
    if limiter:
        limiter.wait()
    if HTTP_LOG_ENABLED:
        LOGGER.info("HTTP GET %s", url)
    try:
        response = session.get(url, timeout=timeout, stream=stream, **kwargs)
        response.raise_for_status()
        if HTTP_LOG_ENABLED:
            LOGGER.info("HTTP GET %s -> %s", url, response.status_code)
        return response
    except requests.RequestException as exc:
        LOGGER.warning("Content download failed for %s: %s", url, exc)
        return None


def request_text(
    session: requests.Session,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    timeout: int = 30,
    **kwargs: Any,
) -> str | None:
    if limiter:
        limiter.wait()
    if HTTP_LOG_ENABLED:
        LOGGER.info("HTTP %s %s params=%s", method, url, _sanitize_for_log(kwargs.get("params")))
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        if HTTP_LOG_ENABLED:
            LOGGER.info("HTTP %s %s -> %s", method, url, response.status_code)
        text = response.text
        if HTTP_LOG_PAYLOADS and text:
            LOGGER.debug("HTTP %s response=%s", url, _sanitize_for_log(text))
        return text
    except requests.RequestException as exc:
        LOGGER.warning("Request failed for %s: %s", url, exc)
        return None
