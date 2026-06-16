"""Shared retry wrapper for hosted providers (DESIGN.md §4.4).

Rate-limit and transient (network/5xx) failures are retried with capped
exponential backoff and full jitter; auth and invalid-request errors are not
retryable and propagate immediately. The sleep function is injectable so tests
exercise the retry logic without real delays.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from crucible.providers.errors import ProviderRateLimitError, ProviderTransientError

T = TypeVar("T")

_RETRYABLE = (ProviderRateLimitError, ProviderTransientError)


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 4,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    rng: random.Random | None = None,
) -> T:
    """Call ``fn`` with retries on rate-limit/transient errors. Re-raises the
    last error once attempts are exhausted; non-retryable errors propagate on
    the first try."""
    sleep = sleep or asyncio.sleep
    jitter = rng or random.Random()
    attempt = 0
    while True:
        try:
            return await fn()
        except _RETRYABLE:
            attempt += 1
            if attempt >= max_attempts:
                raise
            backoff = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            await sleep(jitter.uniform(0.0, backoff))  # full jitter
