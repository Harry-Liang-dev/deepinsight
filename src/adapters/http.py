"""Bounded HTTP transport used by authorized public data providers."""

from __future__ import annotations

import gzip
import time
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.adapters.base import ProviderUnavailableError


@dataclass(frozen=True, slots=True)
class ProviderHTTPResponse:
    """Minimal provider-independent HTTP response."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class ProviderHTTPTransport(Protocol):
    """Injectable HTTP transport for offline tests."""

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        """Send one request and return status, headers, and bytes."""
        ...


class UrllibHTTPTransport:
    """Standard-library HTTPS transport."""

    def send(self, request: Request, timeout: float) -> ProviderHTTPResponse:
        """Send one request without applying retries."""

        try:
            with urlopen(request, timeout=timeout) as response:
                return ProviderHTTPResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            headers = {} if exc.headers is None else dict(exc.headers.items())
            return ProviderHTTPResponse(
                status_code=exc.code,
                headers=headers,
                body=exc.read(),
            )


class ProviderHTTPClient:
    """Apply identity, timeout, rate limiting, and finite retries."""

    _RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        user_agent: str,
        request_timeout: float,
        max_retries: int,
        requests_per_second: float,
        backoff_base_seconds: float = 0.5,
        max_backoff_seconds: float = 30.0,
        transport: ProviderHTTPTransport | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        """Configure deterministic request governance.

        Args:
            user_agent: Declared application identity.
            request_timeout: Timeout passed to every transport call.
            max_retries: Maximum additional attempts after the first request.
            requests_per_second: Per-client request ceiling.
            backoff_base_seconds: Initial exponential retry delay.
            max_backoff_seconds: Upper bound for one retry delay.
            transport: Optional transport injected by offline tests.
            clock: Optional monotonic clock injected by offline tests.
            wall_clock: Optional Unix clock used for rate-limit reset headers.
            sleeper: Optional sleep function injected by offline tests.
        """

        if not user_agent.strip():
            raise ValueError("provider user agent is required")
        if request_timeout <= 0:
            raise ValueError("provider request timeout must be positive")
        if max_retries < 0:
            raise ValueError("provider max_retries cannot be negative")
        if requests_per_second <= 0:
            raise ValueError("provider requests_per_second must be positive")
        if backoff_base_seconds < 0:
            raise ValueError("provider retry backoff cannot be negative")
        if max_backoff_seconds <= 0:
            raise ValueError("provider maximum backoff must be positive")
        self._user_agent = user_agent.strip()
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._backoff_base_seconds = backoff_base_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._transport = transport or UrllibHTTPTransport()
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._sleeper = sleeper or time.sleep
        self._rate_lock = Lock()
        self._last_request_at: float | None = None
        self._request_count = 0
        self._retry_count = 0

    @property
    def request_count(self) -> int:
        """Return physical HTTP attempts made by this client instance."""

        return self._request_count

    @property
    def retry_count(self) -> int:
        """Return attempts made after an initial endpoint request."""

        return self._retry_count

    def get_text(
        self,
        url: str,
        *,
        accept: str,
        headers: Mapping[str, str] | None = None,
        status_error_factory: (
            Callable[[int, str], ProviderUnavailableError] | None
        ) = None,
    ) -> str:
        """Fetch and decode one HTTPS resource.

        Args:
            url: Authorized HTTPS provider URL.
            accept: Explicit accepted response media types.
            headers: Additional provider authentication headers. Values are
                sent only to the requested endpoint and never included in
                raised errors.
            status_error_factory: Optional provider-specific conversion of a
                decoded non-success response into a sanitized public error.

        Returns:
            Decoded UTF-8 response text.

        Raises:
            ProviderUnavailableError: If all bounded attempts fail or the
                provider returns a non-success response.
        """

        if not url.startswith("https://"):
            raise ValueError("provider URL must use HTTPS")
        request_headers = {
            "User-Agent": self._user_agent,
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
        }
        for name, value in (headers or {}).items():
            if (
                not name.strip()
                or name.casefold()
                in {"user-agent", "accept", "accept-encoding", "host"}
                or "\r" in name
                or "\n" in name
                or "\r" in value
                or "\n" in value
            ):
                raise ValueError("invalid additional provider HTTP header")
            request_headers[name] = value
        request = Request(
            url,
            headers=request_headers,
            method="GET",
        )
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            self._wait_for_rate_limit()
            self._request_count += 1
            if attempt > 0:
                self._retry_count += 1
            try:
                response = self._transport.send(
                    request,
                    self._request_timeout,
                )
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 == attempts:
                    raise ProviderUnavailableError(
                        f"provider request failed after {attempts} attempts"
                    ) from exc
                self._sleep_before_retry(attempt, None)
                continue

            if 200 <= response.status_code < 300:
                try:
                    return decode_http_payload(
                        response.body,
                        _header(response.headers, "Content-Encoding") or "",
                    )
                except (OSError, zlib.error) as exc:
                    raise ProviderUnavailableError(
                        "provider response decoding failed"
                    ) from exc
            if (
                response.status_code not in self._RETRYABLE_STATUS_CODES
                or attempt + 1 == attempts
            ):
                if status_error_factory is not None:
                    try:
                        error_text = decode_http_payload(
                            response.body,
                            _header(response.headers, "Content-Encoding") or "",
                        )
                    except (OSError, UnicodeError, zlib.error):
                        error_text = ""
                    raise status_error_factory(response.status_code, error_text)
                raise ProviderUnavailableError(
                    "provider request failed with HTTP status "
                    f"{response.status_code}"
                )
            self._sleep_before_retry(
                attempt,
                response.headers,
            )

        raise AssertionError("bounded provider retry loop did not terminate")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            now = self._clock()
            if self._last_request_at is not None:
                wait_seconds = self._last_request_at + self._minimum_interval - now
                if wait_seconds > 0:
                    self._sleeper(wait_seconds)
                    now = self._clock()
            self._last_request_at = now

    def _sleep_before_retry(
        self,
        attempt: int,
        headers: Mapping[str, str] | None,
    ) -> None:
        retry_after_seconds = _retry_after_seconds(
            None if headers is None else _header(headers, "Retry-After")
        )
        reset_seconds = _rate_limit_reset_seconds(
            None if headers is None else _header(headers, "X-RateLimit-Reset"),
            now=self._wall_clock(),
        )
        delay = (
            retry_after_seconds
            if retry_after_seconds is not None
            else (
                reset_seconds
                if reset_seconds is not None
                else self._backoff_base_seconds * (2**attempt)
            )
        )
        self._sleeper(min(delay, self._max_backoff_seconds))


def decode_http_payload(payload: bytes, content_encoding: str) -> str:
    """Decode gzip, deflate, or plain provider payload bytes."""

    encoding = content_encoding.lower().strip()
    if encoding == "gzip":
        payload = gzip.decompress(payload)
    elif encoding == "deflate":
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            payload = zlib.decompress(payload, -zlib.MAX_WBITS)
    return payload.decode("utf-8", errors="replace")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            return value
    return None


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized.isdigit():
        return None
    return float(normalized)


def _rate_limit_reset_seconds(
    value: str | None,
    *,
    now: float,
) -> float | None:
    if value is None:
        return None
    try:
        reset_at = float(value.strip())
    except ValueError:
        return None
    delay = reset_at - now
    return delay if delay > 0 else None
