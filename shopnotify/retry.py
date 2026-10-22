"""Retry wrapper with exponential backoff and rate-limit handling.

Used around every outbound API call. The rules:

- Retry on connection/timeout errors, HTTP 5xx and HTTP 429.
- On 429, wait at least as long as the server's Retry-After asks for.
- Backoff doubles each attempt with jitter, capped at ``max_delay``.
- Anything else (4xx client errors, bugs) fails immediately.
"""

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE = (ConnectionError, TimeoutError)


class RateLimitError(Exception):
    """HTTP 429. ``retry_after`` is the server-provided wait in seconds."""

    def __init__(self, message: str = "rate limited",
                 retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TransientError(Exception):
    """HTTP 5xx or another failure worth retrying."""


def retry_call(fn: Callable[[], T], *, max_attempts: int = 3,
               base_delay: float = 0.5, max_delay: float = 30.0,
               sleep: Callable[[float], None] = time.sleep,
               jitter: Callable[[float, float], float] = random.uniform) -> T:
    """Call ``fn`` until it succeeds or the attempts run out.

    ``sleep`` and ``jitter`` are injectable so tests can run instantly
    and assert on the exact delays.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (RateLimitError, TransientError, *RETRYABLE) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(base_delay * 2 ** (attempt - 1), max_delay)
            delay += jitter(0, base_delay)
            if isinstance(exc, RateLimitError) and exc.retry_after:
                delay = max(delay, exc.retry_after)
            logger.warning("attempt %d failed (%s); retrying in %.2fs",
                           attempt, exc, delay)
            sleep(delay)
    raise last_error
