from __future__ import annotations

import pytest

import crucible.eval.run as run_module
from crucible.config import PrivacySuiteConfig, SuitesConfig
from crucible.eval.run import _guard, run_eval
from crucible.eval.types import SuiteResult

from ...conftest import make_fake_spec


async def test_guard_returns_failed_suite_when_fail_fast_is_disabled() -> None:
    async def fail() -> SuiteResult:
        raise ValueError("broken suite")

    result = await _guard("retrieval", fail(), fail_fast=False)
    assert result.status == "failed"
    assert result.error == "ValueError: broken suite"
    assert result.metrics == ()
    assert result.records == ()


async def test_guard_propagates_when_fail_fast_is_enabled() -> None:
    async def fail() -> SuiteResult:
        raise ValueError("broken suite")

    with pytest.raises(ValueError, match="broken suite"):
        await _guard("retrieval", fail(), fail_fast=True)


async def test_run_eval_rejects_a_spec_without_suites(tmp_path) -> None:
    spec = make_fake_spec(tmp_path)
    with pytest.raises(ValueError, match="no evaluation suites"):
        await run_eval(spec, object())  # type: ignore[arg-type]


async def test_run_eval_selects_privacy_suite_seed_and_generator_warmup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = make_fake_spec(tmp_path)
    spec = base.model_copy(update={"suites": SuitesConfig(privacy=PrivacySuiteConfig(canaries=1))})
    warmups: list[bool] = []
    received_seeds: list[int] = []

    class Pipeline:
        async def warmup(self, *, generator: bool = True) -> None:
            warmups.append(generator)

    async def privacy_suite(
        pipeline, spec_arg, config, seed, collector, *, concurrency  # type: ignore[no-untyped-def]
    ) -> SuiteResult:
        received_seeds.append(seed)
        return SuiteResult(suite="privacy", metrics=(), records=())

    monkeypatch.setattr(run_module, "build_pipeline", lambda spec_arg, index: Pipeline())
    monkeypatch.setattr(run_module, "run_privacy_suite", privacy_suite)
    monkeypatch.setattr(run_module, "_now", lambda: "2026-01-01T00:00:00+00:00")

    result = await run_eval(spec, object())  # type: ignore[arg-type]
    assert warmups == [True]
    assert received_seeds == [spec.seed + 4]
    assert [suite.suite for suite in result.suites] == ["privacy"]
