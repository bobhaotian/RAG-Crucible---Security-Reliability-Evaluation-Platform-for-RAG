from __future__ import annotations

import pytest

import crucible.obs.timing as timing_module
from crucible.obs.aggregate import TimingCollector, _percentile
from crucible.obs.timing import StageTimer


def test_percentile_uses_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    assert _percentile(values, 0.5) == 2.0
    assert _percentile(values, 0.95) == 5.0


def test_timing_collector_aggregates_and_sorts_stages() -> None:
    collector = TimingCollector()
    collector.add("retrieve", 10.0)
    collector.add_all({"retrieve": 20.0, "embed": 5.0})

    stats = collector.stats()

    assert [item.stage for item in stats] == ["embed", "retrieve"]
    assert stats[1].count == 2
    assert stats[1].mean_ms == 15.0
    assert stats[1].p50_ms == 10.0
    assert stats[1].p95_ms == 20.0


def test_timing_collector_empty_has_no_stats() -> None:
    assert TimingCollector().stats() == []


def test_stage_timer_records_success_and_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    readings = iter([1.0, 1.025, 2.0, 2.01])
    monkeypatch.setattr(timing_module.time, "perf_counter", lambda: next(readings))
    timer = StageTimer()

    with timer.stage("first"):
        pass
    with pytest.raises(RuntimeError), timer.stage("failed"):
        raise RuntimeError("boom")

    assert timer.get("first") == pytest.approx(25.0)
    assert timer.get("failed") == pytest.approx(10.0)
    assert timer.total_ms() == pytest.approx(35.0)
    assert timer.as_dict() == {"first": pytest.approx(25.0), "failed": pytest.approx(10.0)}
