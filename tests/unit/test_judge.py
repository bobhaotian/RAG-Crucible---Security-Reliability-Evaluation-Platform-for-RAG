"""Judge behavior: heuristic verdicts, LLM parsing, cache modes."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from crucible.eval.judge import (
    HeuristicJudge,
    JudgeCache,
    JudgeCacheMissError,
    LlmJudge,
)
from crucible.providers import GenerateResult, GenParams, Message, Usage

CONTEXT = "The AT-300 has a battery life of 14 hours. It weighs 30 kg."


class StubGenerator:
    """Scripted judge model; counts calls so cache behavior is observable."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def generate(self, messages: Sequence[Message], *, params: GenParams) -> GenerateResult:
        self.calls += 1
        return GenerateResult(text=self.reply, model="stub", usage=Usage())


async def test_heuristic_judge_supports_contained_claims() -> None:
    judge = HeuristicJudge()
    supported = await judge.supports("The AT-300 battery life is 14 hours.", CONTEXT)
    unsupported = await judge.supports(
        "The AT-300 includes a free espresso machine warranty.", CONTEXT
    )
    assert supported.supported and supported.parse_ok
    assert not unsupported.supported


async def test_llm_judge_parses_yes_no() -> None:
    yes = LlmJudge(StubGenerator("YES"), model="m", mode="live", cache=None)
    no = LlmJudge(StubGenerator("No, it does not."), model="m", mode="live", cache=None)
    assert (await yes.supports("claim", CONTEXT)).supported
    verdict = await no.supports("claim", CONTEXT)
    assert not verdict.supported and verdict.parse_ok


async def test_llm_judge_unparseable_falls_back_to_heuristic_flagged() -> None:
    judge = LlmJudge(StubGenerator("As an AI model..."), model="m", mode="live", cache=None)
    verdict = await judge.supports("The AT-300 battery life is 14 hours.", CONTEXT)
    assert not verdict.parse_ok
    assert verdict.supported  # heuristic fallback found the tokens in context


async def test_auto_mode_judges_once_then_hits_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "judgments.jsonl"
    generator = StubGenerator("YES")
    judge = LlmJudge(generator, model="m", mode="auto", cache=JudgeCache(cache_path))
    first = await judge.supports("claim", CONTEXT)
    second = await judge.supports("claim", CONTEXT)
    assert generator.calls == 1
    assert not first.cached and second.cached
    assert second.supported

    # a fresh process (new cache object) reads the persisted judgment
    reloaded = LlmJudge(StubGenerator("NO"), model="m", mode="auto", cache=JudgeCache(cache_path))
    assert (await reloaded.supports("claim", CONTEXT)).supported


async def test_cached_mode_misses_are_errors(tmp_path: Path) -> None:
    judge = LlmJudge(
        StubGenerator("YES"),
        model="m",
        mode="cached",
        cache=JudgeCache(tmp_path / "empty.jsonl"),
    )
    with pytest.raises(JudgeCacheMissError, match=r"judge\.mode=auto"):
        await judge.supports("claim", CONTEXT)


async def test_live_mode_rejudges_and_refreshes(tmp_path: Path) -> None:
    cache_path = tmp_path / "judgments.jsonl"
    cache = JudgeCache(cache_path)
    first = LlmJudge(StubGenerator("YES"), model="m", mode="live", cache=cache)
    await first.supports("claim", CONTEXT)

    flipped = StubGenerator("NO")
    second = LlmJudge(flipped, model="m", mode="live", cache=JudgeCache(cache_path))
    verdict = await second.supports("claim", CONTEXT)
    assert flipped.calls == 1
    assert not verdict.supported
    # last write wins on reload
    assert JudgeCache(cache_path).get(second._key("claim", CONTEXT)) is False


async def test_cache_key_separates_models_and_inputs(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "judgments.jsonl")
    judge_a = LlmJudge(StubGenerator("YES"), model="model-a", mode="auto", cache=cache)
    judge_b = LlmJudge(StubGenerator("NO"), model="model-b", mode="auto", cache=cache)
    assert (await judge_a.supports("claim", CONTEXT)).supported
    assert not (await judge_b.supports("claim", CONTEXT)).supported
