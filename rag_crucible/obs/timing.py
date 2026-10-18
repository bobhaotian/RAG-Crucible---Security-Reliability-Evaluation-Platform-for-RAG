"""Per-stage wall-clock timing for a single pipeline invocation.

The runner (Phase 3) aggregates these per-query timings into p50/p95 per
stage per run; until then the CLI prints them per answer.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class StageTimer:
    def __init__(self) -> None:
        self._elapsed_ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self._elapsed_ms[name] = (time.perf_counter() - start) * 1000.0

    def get(self, name: str) -> float | None:
        return self._elapsed_ms.get(name)

    def total_ms(self) -> float:
        return sum(self._elapsed_ms.values())

    def as_dict(self) -> dict[str, float]:
        return dict(self._elapsed_ms)
