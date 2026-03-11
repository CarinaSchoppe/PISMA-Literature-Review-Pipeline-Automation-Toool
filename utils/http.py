"""HTTP session, retry, throttling, and persistent response-cache utilities."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
HTTP_LOG_ENABLED = True
HTTP_LOG_PAYLOADS = True
BackoffStrategy = Literal["fixed", "linear", "exponential"]


@dataclass
class _HttpRuntimeConfig:
    """In-process HTTP runtime tuning shared by all request helpers."""

    cache_enabled: bool = False
    cache_dir: Path = Path("data/http_cache")
    cache_ttl_seconds: int = 86_400
    retry_max_attempts: int = 4
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 30.0


HTTP_RUNTIME_CONFIG = _HttpRuntimeConfig()


def configure_http_logging(*, enabled: bool, log_payloads: bool) -> None:
    """Configure HTTP request logging for the current process."""

    global HTTP_LOG_ENABLED, HTTP_LOG_PAYLOADS
    HTTP_LOG_ENABLED = enabled
    HTTP_LOG_PAYLOADS = log_payloads


def configure_http_runtime(
    *,
    cache_enabled: bool,
    cache_dir: str | Path,
    cache_ttl_seconds: int,
    retry_max_attempts: int,
    retry_base_delay_seconds: float,
    retry_max_delay_seconds: float,
) -> None:
    """Configure process-wide caching and backoff settings for the request helpers."""

    global HTTP_RUNTIME_CONFIG
    resolved_cache_dir = Path(cache_dir)
    if cache_enabled:
        resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    HTTP_RUNTIME_CONFIG = _HttpRuntimeConfig(
        cache_enabled=cache_enabled,
        cache_dir=resolved_cache_dir,
        cache_ttl_seconds=max(int(cache_ttl_seconds), 1),
        retry_max_attempts=max(int(retry_max_attempts), 1),
        retry_base_delay_seconds=max(float(retry_base_delay_seconds), 0.0),
        retry_max_delay_seconds=max(float(retry_max_delay_seconds), 0.0),
    )


def _sanitize_for_log(value: Any) -> Any:
    """Redact secrets and truncate oversized values before they reach logs."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key == "key" or any(token in normalized_key for token in ("authorization", "api_key", "apikey", "token")):
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
    """Simple per-process rate limiter shared by API clients."""

    def __init__(
        self,
        calls_per_second: float = 1.0,
        *,
        max_requests_per_minute: int | None = None,
        request_delay_seconds: float = 0.0,
    ) -> None:
        self.min_interval = 1.0 / calls_per_second if calls_per_second > 0 else 0.0
        self.max_requests_per_minute = max(int(max_requests_per_minute), 1) if max_requests_per_minute else None
        self.request_delay_seconds = max(float(request_delay_seconds), 0.0)
        self._lock = Lock()
        self._last_call = 0.0
        self._request_history: deque[float] = deque()

    def wait(self) -> None:
        """Sleep just long enough to respect the configured minimum call interval."""

        if self.min_interval <= 0 and self.request_delay_seconds <= 0 and self.max_requests_per_minute is None:
            return
        with self._lock:
            now = time.monotonic()
            self._prune_history(now)
            wait_seconds = 0.0
            if self.min_interval > 0:
                wait_seconds = max(wait_seconds, self.min_interval - (now - self._last_call))
            if self.request_delay_seconds > 0:
                wait_seconds = max(wait_seconds, self.request_delay_seconds - (now - self._last_call))
            if self.max_requests_per_minute is not None and len(self._request_history) >= self.max_requests_per_minute:
                oldest = self._request_history[0]
                wait_seconds = max(wait_seconds, 60.0 - (now - oldest))
            if wait_seconds > 0:
                time.sleep(wait_seconds)
                now = time.monotonic()
                self._prune_history(now)
            self._last_call = now
            if self.max_requests_per_minute is not None:
                self._request_history.append(now)

    def _prune_history(self, now: float) -> None:
        """Drop request timestamps that are older than the rolling one-minute window."""

        if self.max_requests_per_minute is None:
            return
        while self._request_history and (now - self._request_history[0]) >= 60.0:
            self._request_history.popleft()


class PersistentResponseCache:
    """Store small GET responses on disk so repeated discovery runs can reuse them."""

    def __init__(self, root_dir: Path, ttl_seconds: int) -> None:
        self.root_dir = Path(root_dir)
        self.ttl_seconds = max(int(ttl_seconds), 1)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def load(self, cache_key: str, *, expected_kind: str) -> Any | None:
        """Load a cached payload when it exists, matches the expected type, and is still fresh."""

        path = self.root_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        created_at = float(payload.get("created_at", 0.0) or 0.0)
        if (time.time() - created_at) > self.ttl_seconds:
            return None
        if payload.get("kind") != expected_kind:
            return None
        return payload.get("payload")

    def store(self, cache_key: str, *, kind: str, payload: Any) -> None:
        """Persist a cacheable response payload using a stable file name."""

        path = self.root_dir / f"{cache_key}.json"
        path.write_text(
            json.dumps(
                {
                    "created_at": time.time(),
                    "kind": kind,
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def build_session(user_agent: str, extra_headers: dict[str, str] | None = None) -> requests.Session:
    """Create a resilient HTTP session with retries and a consistent user agent."""

    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
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
    use_cache: bool | None = None,
    retry_max_attempts: int | None = None,
    retry_backoff_strategy: BackoffStrategy = "exponential",
    retry_base_delay_seconds: float | None = None,
    **kwargs: Any,
) -> Any:
    """Perform an HTTP request and parse the response body as JSON when successful."""

    if HTTP_LOG_ENABLED:
        LOGGER.info(
            "HTTP %s %s params=%s",
            method,
            url,
            _sanitize_for_log(kwargs.get("params")),
        )
        if HTTP_LOG_PAYLOADS and "json" in kwargs:
            LOGGER.debug("HTTP %s payload=%s", url, _sanitize_for_log(kwargs.get("json")))

    cached_payload = _load_cached_payload(method, url, expected_kind="json", use_cache=use_cache, kwargs=kwargs)
    if cached_payload is not None:
        return cached_payload

    try:
        response = _request_with_backoff(
            session,
            method,
            url,
            limiter=limiter,
            timeout=timeout,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_strategy=retry_backoff_strategy,
            retry_base_delay_seconds=retry_base_delay_seconds,
            **kwargs,
        )
        if response is None:
            return None
        if HTTP_LOG_ENABLED:
            LOGGER.info("HTTP %s %s -> %s", method, url, response.status_code)
        if not response.content:
            return None
        payload = response.json()
        if HTTP_LOG_PAYLOADS:
            LOGGER.debug("HTTP %s response=%s", url, _sanitize_for_log(payload))
        _store_cached_payload(method, url, kind="json", payload=payload, use_cache=use_cache, kwargs=kwargs)
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
    retry_max_attempts: int | None = None,
    retry_backoff_strategy: BackoffStrategy = "exponential",
    retry_base_delay_seconds: float | None = None,
    **kwargs: Any,
) -> requests.Response | None:
    """Perform an HTTP GET request intended for binary content such as PDFs."""

    if HTTP_LOG_ENABLED:
        LOGGER.info("HTTP GET %s", url)
    try:
        response = _request_with_backoff(
            session,
            "GET",
            url,
            limiter=limiter,
            timeout=timeout,
            stream=stream,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_strategy=retry_backoff_strategy,
            retry_base_delay_seconds=retry_base_delay_seconds,
            **kwargs,
        )
        if response is None:
            return None
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
    use_cache: bool | None = None,
    retry_max_attempts: int | None = None,
    retry_backoff_strategy: BackoffStrategy = "exponential",
    retry_base_delay_seconds: float | None = None,
    **kwargs: Any,
) -> str | None:
    """Perform an HTTP request and return the raw text body on success."""

    if HTTP_LOG_ENABLED:
        LOGGER.info("HTTP %s %s params=%s", method, url, _sanitize_for_log(kwargs.get("params")))

    cached_text = _load_cached_payload(method, url, expected_kind="text", use_cache=use_cache, kwargs=kwargs)
    if cached_text is not None:
        return str(cached_text)

    try:
        response = _request_with_backoff(
            session,
            method,
            url,
            limiter=limiter,
            timeout=timeout,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_strategy=retry_backoff_strategy,
            retry_base_delay_seconds=retry_base_delay_seconds,
            **kwargs,
        )
        if response is None:
            return None
        if HTTP_LOG_ENABLED:
            LOGGER.info("HTTP %s %s -> %s", method, url, response.status_code)
        text = response.text
        if HTTP_LOG_PAYLOADS and text:
            LOGGER.debug("HTTP %s response=%s", url, _sanitize_for_log(text))
        _store_cached_payload(method, url, kind="text", payload=text, use_cache=use_cache, kwargs=kwargs)
        return text
    except requests.RequestException as exc:
        LOGGER.warning("Request failed for %s: %s", url, exc)
        return None


def _request_with_backoff(
    session: requests.Session,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    timeout: int,
    retry_max_attempts: int | None = None,
    retry_backoff_strategy: BackoffStrategy = "exponential",
    retry_base_delay_seconds: float | None = None,
    **kwargs: Any,
) -> requests.Response | None:
    """Perform one request with explicit 429-aware backoff that respects `Retry-After`."""

    attempts = max(int(retry_max_attempts or HTTP_RUNTIME_CONFIG.retry_max_attempts), 1)
    for attempt in range(1, attempts + 1):
        if limiter:
            limiter.wait()
        response = session.request(method, url, timeout=timeout, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt >= attempts:
            response.raise_for_status()
            return None
        delay_seconds = _calculate_backoff_delay(
            response,
            attempt,
            strategy=retry_backoff_strategy,
            base_delay_seconds=retry_base_delay_seconds,
        )
        LOGGER.warning(
            "HTTP %s %s returned 429. Backing off for %.2f seconds before retry %s/%s using %s strategy.",
            method,
            url,
            delay_seconds,
            attempt + 1,
            attempts,
            retry_backoff_strategy,
        )
        time.sleep(delay_seconds)
    return None


def _calculate_backoff_delay(
    response: requests.Response,
    attempt: int,
    *,
    strategy: BackoffStrategy = "exponential",
    base_delay_seconds: float | None = None,
) -> float:
    """Calculate the next delay using `Retry-After` when present, otherwise the chosen backoff strategy."""

    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), HTTP_RUNTIME_CONFIG.retry_max_delay_seconds)
        except ValueError:
            pass
    resolved_base = HTTP_RUNTIME_CONFIG.retry_base_delay_seconds if base_delay_seconds is None else max(float(base_delay_seconds), 0.0)
    if resolved_base <= 0:
        return 0.0
    if strategy == "fixed":
        delay = resolved_base
    elif strategy == "linear":
        delay = resolved_base * attempt
    else:
        delay = resolved_base * (2 ** max(attempt - 1, 0))
    return min(delay, HTTP_RUNTIME_CONFIG.retry_max_delay_seconds)


def _load_cached_payload(
    method: str,
    url: str,
    *,
    expected_kind: str,
    use_cache: bool | None,
    kwargs: dict[str, Any],
) -> Any | None:
    """Load a cached GET response when request caching is enabled."""

    if not _should_use_cache(method, use_cache):
        return None
    cache = PersistentResponseCache(HTTP_RUNTIME_CONFIG.cache_dir, HTTP_RUNTIME_CONFIG.cache_ttl_seconds)
    cache_key = _build_cache_key(method, url, kwargs)
    cached_payload = cache.load(cache_key, expected_kind=expected_kind)
    if cached_payload is not None and HTTP_LOG_ENABLED:
        LOGGER.info("HTTP cache hit for %s %s", method, url)
    return cached_payload


def _store_cached_payload(
    method: str,
    url: str,
    *,
    kind: str,
    payload: Any,
    use_cache: bool | None,
    kwargs: dict[str, Any],
) -> None:
    """Store a fresh cache entry for GET requests when request caching is enabled."""

    if not _should_use_cache(method, use_cache):
        return
    cache = PersistentResponseCache(HTTP_RUNTIME_CONFIG.cache_dir, HTTP_RUNTIME_CONFIG.cache_ttl_seconds)
    cache.store(_build_cache_key(method, url, kwargs), kind=kind, payload=payload)


def _should_use_cache(method: str, use_cache: bool | None) -> bool:
    """Decide whether the current request is eligible for on-disk response caching."""

    if use_cache is not None:
        return bool(use_cache)
    return HTTP_RUNTIME_CONFIG.cache_enabled and method.upper() == "GET"


def _build_cache_key(method: str, url: str, kwargs: dict[str, Any]) -> str:
    """Hash the effective request signature into a stable cache key."""

    payload = {
        "method": method.upper(),
        "url": url,
        "params": kwargs.get("params"),
        "json": kwargs.get("json"),
        "data": kwargs.get("data"),
        "headers": kwargs.get("headers"),
    }
    serialized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
