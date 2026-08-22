from __future__ import annotations

import asyncio

import pytest

from crucible.eval.concurrent import bounded_gather


async def test_bounded_gather_preserves_input_order() -> None:
    async def finish_after(value: int, delay: float) -> int:
        await asyncio.sleep(delay)
        return value

    results = await bounded_gather(
        [
            finish_after(1, 0.03),
            finish_after(2, 0.01),
            finish_after(3, 0.0),
        ],
        limit=3,
    )

    assert results == [1, 2, 3]


async def test_bounded_gather_never_exceeds_limit() -> None:
    active = 0
    peak = 0

    async def observe_concurrency(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value

    results = await bounded_gather(
        [observe_concurrency(value) for value in range(6)],
        limit=2,
    )

    assert results == list(range(6))
    assert peak == 2


async def test_bounded_gather_propagates_task_failure() -> None:
    async def fail() -> None:
        raise RuntimeError("task failed")

    with pytest.raises(RuntimeError, match="task failed"):
        await bounded_gather([fail()], limit=1)
