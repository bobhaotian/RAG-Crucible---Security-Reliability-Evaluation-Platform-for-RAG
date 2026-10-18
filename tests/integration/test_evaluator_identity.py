"""Evaluator identity must not reach the system under test.

The suites know which documents they planted; the pipeline must not. Every
retrieved chunk's source is printed into the prompt and handed to every
defense, so a labelled path (``__poison__/q007.md``) is an answer key. Measured
on Qwen2.5-0.5B, hiding the canary path alone moved privacy leakage under no
defense from 5/27 to 10/27 in one run, so the generator does read it.

This runs the security and privacy suites end to end on the fake provider over
the seeded corpus and records what the system under test actually received:
every generator prompt and every chunk passed to a defense. The fake
generator's own block parser skips the source, which is why no metric could
show this and the prompts have to be read directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import rag_crucible.eval.security as security
import rag_crucible.pipeline.rag as rag
from rag_crucible.config import SuitesConfig, load_spec
from rag_crucible.eval import EvalRunResult, run_eval
from rag_crucible.index import FaissIndex
from rag_crucible.ingest import build_index, load_corpus
from rag_crucible.providers import GenerateResult, GenParams, Message
from rag_crucible.providers.fake import FakeGenerator
from rag_crucible.types import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]

# The labels the suites used to give planted documents.
EVALUATOR_LABELS = ("__poison__", "__inject__", "__canary__")


@dataclass
class Exposure:
    """What the system under test was shown, by entry point."""

    prompts: list[str] = field(default_factory=list)
    chunks: dict[str, list[Chunk]] = field(default_factory=dict)


@pytest.fixture
def exposure(monkeypatch: pytest.MonkeyPatch) -> Exposure:
    seen = Exposure()
    generate = FakeGenerator.generate

    async def recording_generate(
        self: FakeGenerator, messages: Sequence[Message], *, params: GenParams
    ) -> GenerateResult:
        seen.prompts.append("\n".join(message.content for message in messages))
        return await generate(self, messages, params=params)

    monkeypatch.setattr(FakeGenerator, "generate", recording_generate)

    # Patched where the caller looks the name up at call time, so the real
    # pipeline and suite reach the recorder without any change to either.
    def spy(module: Any, name: str, chunks_of: Callable[..., list[Chunk]]) -> None:
        original = getattr(module, name)

        def recording(*args: Any, **kwargs: Any) -> Any:
            seen.chunks.setdefault(name, []).extend(chunks_of(*args, **kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, recording)

    def candidates(context: Any, *_: Any, **__: Any) -> list[Chunk]:
        return [candidate.chunk for candidate in context.candidates]

    spy(rag, "filter_injected_chunks", candidates)
    spy(rag, "filter_untrusted_chunks", candidates)
    spy(rag, "resolve_numeric_conflicts", lambda query, context: candidates(context))
    spy(security, "clean_chunk_screening_reason", lambda chunk, defense: [chunk])
    return seen


async def _run_seeded(tmp_path: Path) -> EvalRunResult:
    """smoke-fake's security and privacy suites, with every defense arm on so
    each defense entry point is exercised."""
    spec = load_spec(REPO_ROOT / "specs" / "smoke-fake.yaml")
    assert spec.suites is not None and spec.suites.security is not None
    security_config = spec.suites.security.model_copy(
        update={
            "defenses": ("none", "prompt_isolation", "injection_filter", "answer_integrity"),
        }
    )
    spec = spec.model_copy(
        update={
            "suites": SuitesConfig(security=security_config, privacy=spec.suites.privacy),
        }
    )
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    return await run_eval(spec, index)


async def test_no_prompt_or_defense_input_names_a_planted_document(
    tmp_path: Path, exposure: Exposure
) -> None:
    result = await _run_seeded(tmp_path)
    assert {suite.suite for suite in result.suites} == {"security", "privacy"}

    # Planted text did reach the prompts, so a clean result is not vacuous.
    joined = "\n".join(exposure.prompts)
    assert "This figure supersedes earlier documentation." in joined  # poison
    assert "OWNED-" in joined  # injection
    assert "@example-corp.test" in joined  # canary

    for prompt in exposure.prompts:
        for label in EVALUATOR_LABELS:
            assert label not in prompt, f"prompt names a planted document: {label}"
        assert "(source: __" not in prompt

    assert set(exposure.chunks) == {
        "filter_injected_chunks",
        "filter_untrusted_chunks",
        "resolve_numeric_conflicts",
        "clean_chunk_screening_reason",
    }
    docs, _ = load_corpus(REPO_ROOT / "datasets" / "seeded" / "corpus")
    corpus_ids = {doc.doc_id for doc in docs}
    corpus_sources = {doc.source for doc in docs}
    for name, chunks in exposure.chunks.items():
        for chunk in chunks:
            assert not chunk.source.startswith("__"), f"{name} saw {chunk.source}"
            assert not any(label in chunk.source for label in EVALUATOR_LABELS)
        planted = {chunk.source for chunk in chunks if chunk.doc_id not in corpus_ids}
        # A planted document never borrows a real document's path.
        assert not planted & corpus_sources
        if name != "clean_chunk_screening_reason":  # that one screens clean chunks only
            assert planted, f"{name} never received a planted chunk"
