"""Aggregate per-query stage timings into per-run p50/p95 statistics."""

from __future__ import annotations

import statistics

from crucible.types import StrictModel


class StageStats(StrictModel):
    stage: str
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; well-defined for any sample size >= 1."""
    rank = max(1, round(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


class TimingCollector:
    """Collects stage→elapsed-ms samples across many pipeline invocations."""

    def __init__(self) -> None:
        self._samples: dict[str, list[float]] = {}

    def add(self, stage: str, elapsed_ms: float) -> None:
        self._samples.setdefault(stage, []).append(elapsed_ms)

    def add_all(self, timings: dict[str, float]) -> None:
        for stage, elapsed_ms in timings.items():
            self.add(stage, elapsed_ms)

    def stats(self) -> list[StageStats]:
        results = []
        for stage in sorted(self._samples):
            values = sorted(self._samples[stage])
            results.append(
                StageStats(
                    stage=stage,
                    count=len(values),
                    mean_ms=round(statistics.fmean(values), 3),
                    p50_ms=round(_percentile(values, 0.50), 3),
                    p95_ms=round(_percentile(values, 0.95), 3),
                )
            )
        return results
