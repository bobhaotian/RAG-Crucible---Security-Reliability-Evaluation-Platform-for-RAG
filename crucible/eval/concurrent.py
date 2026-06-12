"""Bounded concurrency for suite items.

Suite items are independent by construction; ``bounded_gather`` runs them
through a semaphore sized by ``suites.concurrency`` and preserves input order,
so aggregation and records stay deterministic regardless of completion order.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def bounded_gather(coros: list[Coroutine[Any, Any, T]], limit: int) -> list[T]:
    semaphore = asyncio.Semaphore(limit)

    async def run_one(coro: Coroutine[Any, Any, T]) -> T:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run_one(coro) for coro in coros))
