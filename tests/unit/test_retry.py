"""Retry wrapper: retries the retryable, gives up after the cap, passes
non-retryable straight through."""

from __future__ import annotations

import pytest

from crucible.providers.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTransientError,
)
from crucible.providers.retry import with_retries


async def _noop_sleep(_: float) -> None:
    return None


async def test_succeeds_after_transient_failures() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderTransientError("blip")
        return "ok"

    result = await with_retries(fn, max_attempts=4, sleep=_noop_sleep)
    assert result == "ok"
    assert calls == 3


async def test_gives_up_after_max_attempts() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise ProviderRateLimitError("429")

    with pytest.raises(ProviderRateLimitError):
        await with_retries(fn, max_attempts=3, sleep=_noop_sleep)
    assert calls == 3


async def test_non_retryable_errors_propagate_immediately() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise ProviderAuthError("bad key")

    with pytest.raises(ProviderAuthError):
        await with_retries(fn, max_attempts=4, sleep=_noop_sleep)
    assert calls == 1  # not retried
