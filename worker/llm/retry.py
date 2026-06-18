from __future__ import annotations

import time
import urllib.error
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


RETRYABLE_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_CODES
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 2,
    backoff_seconds: tuple[float, ...] = (1.0, 3.0, 8.0),
) -> T:
    last: Exception | None = None
    for attempt in range(max(0, max_retries) + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt >= max_retries or not is_retryable(exc):
                raise
            time.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
    if last is not None:
        raise last
    raise RuntimeError("retry call failed without an exception")
