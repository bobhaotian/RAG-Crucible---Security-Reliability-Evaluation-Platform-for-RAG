"""The RAG pipeline — the system under test.

retrieve → (rerank) → generate, with citations and per-stage timing on every
answer. Eval suites consume this class only through ``answer`` / ``retrieve``;
they never reach into provider or index internals.
"""

from __future__ import annotations

from crucible.config import DefensesConfig, PipelineConfig
from crucible.index import VectorIndex
from crucible.obs import StageTimer
from crucible.pipeline.citations import parse_citations
from crucible.pipeline.consistency import ClaimConflict, resolve_numeric_conflicts
from crucible.pipeline.defenses import filter_injected_chunks, filter_untrusted_chunks
from crucible.pipeline.prompts import build_messages
from crucible.pipeline.types import Answer, Candidate, RankedContext, StageTimings
from crucible.providers import (
    Embedder,
    EmbedInputType,
    Generator,
    GenParams,
    Message,
    Reranker,
    Usage,
)


class RagPipeline:
    def __init__(
        self,
        *,
        config: PipelineConfig,
        embedder: Embedder,
        index: VectorIndex,
        reranker: Reranker | None,
        generator: Generator,
    ) -> None:
        if config.reranker.enabled and reranker is None:
            raise ValueError("config enables reranking but no reranker was provided")
        self._config = config
        self._embedder = embedder
        self._index = index
        self._reranker = reranker
        self._generator = generator

    @property
    def config(self) -> PipelineConfig:
        return self._config

    @property
    def has_reranker(self) -> bool:
        return self._reranker is not None

    @property
    def embedder(self) -> Embedder:
        """Exposed so the security suite can build a poisoned index with the
        same (warmed) embedder instead of reloading the model."""
        return self._embedder

    def with_index(self, index: VectorIndex) -> RagPipeline:
        """A sibling pipeline over a different index, sharing this pipeline's
        providers. The security suite uses it to query a poisoned index without
        reloading models or mutating the clean index."""
        return RagPipeline(
            config=self._config,
            embedder=self._embedder,
            index=index,
            reranker=self._reranker,
            generator=self._generator,
        )

    async def warmup(self, *, generator: bool = True) -> None:
        """Load lazy providers outside any timed path, so first-call model
        loads don't pollute latency stats (p95 >> p50 otherwise)."""
        await self._embedder.embed(["warmup"], input_type=EmbedInputType.QUERY)
        if self._reranker is not None:
            await self._reranker.rerank("warmup", ["warmup"], top_n=1)
        if generator:
            messages = [Message(role="user", content="Reply with OK.")]
            await self._generator.generate(messages, params=GenParams(max_tokens=1))

    async def retrieve(self, query: str, *, timer: StageTimer | None = None) -> list[Candidate]:
        """Embed the query and pull the top-k candidates from the index."""
        timer = timer or StageTimer()
        with timer.stage("embed_query"):
            embedded = await self._embedder.embed([query], input_type=EmbedInputType.QUERY)
        with timer.stage("retrieve"):
            hits = await self._index.search(embedded.vectors[0], self._config.retriever.k)
        return [
            Candidate(chunk=hit.chunk, score=hit.score, rank=rank) for rank, hit in enumerate(hits)
        ]

    async def rerank(
        self,
        query: str,
        candidates: list[Candidate],
        *,
        top_n: int | None = None,
        timer: StageTimer | None = None,
    ) -> list[Candidate]:
        """Reorder candidates with the configured reranker. ``top_n=None``
        keeps the full list — the retrieval suite uses that to measure rerank
        lift at every cutoff, independent of the generation context size."""
        if self._reranker is None:
            raise ValueError("this pipeline has no reranker configured")
        if not candidates:
            return []
        n = len(candidates) if top_n is None else min(top_n, len(candidates))
        timer = timer or StageTimer()
        with timer.stage("rerank"):
            result = await self._reranker.rerank(query, [c.chunk.text for c in candidates], top_n=n)
        return [
            Candidate(chunk=candidates[item.index].chunk, score=item.score, rank=rank)
            for rank, item in enumerate(result.ranking)
        ]

    async def build_context(
        self,
        query: str,
        candidates: list[Candidate],
        *,
        timer: StageTimer | None = None,
    ) -> RankedContext:
        """Apply the (toggleable) rerank stage and cut to top_n."""
        top_n = self._config.reranker.top_n
        if self._config.reranker.enabled and self._reranker is not None and candidates:
            reordered = await self.rerank(query, candidates, top_n=top_n, timer=timer)
            return RankedContext(candidates=reordered, rerank_applied=True)
        return RankedContext(candidates=candidates[:top_n], rerank_applied=False)

    async def answer(self, query: str, *, defenses: DefensesConfig | None = None) -> Answer:
        """Answer through the full pipeline. ``defenses`` overrides the spec's
        configured defenses for this call — the security suite uses it to run
        each defense condition over one warmed pipeline."""
        active = defenses if defenses is not None else self._config.defenses
        timer = StageTimer()
        candidates = await self.retrieve(query, timer=timer)
        context = await self.build_context(query, candidates, timer=timer)
        if active.injection_filter:
            context, _ = filter_injected_chunks(context)
        if active.answer_integrity:
            decision = resolve_numeric_conflicts(query, context)
            if decision.action == "abstain":
                return Answer(
                    text=_conflict_abstention(decision.conflicts),
                    citations=[],
                    context=decision.context,
                    usage=Usage(),
                    timings=_stage_timings(timer),
                )
            context = decision.context
            context, _ = filter_untrusted_chunks(context)
            if not context.candidates:
                return Answer(
                    text=(
                        "The retrieved evidence has no sufficiently trusted source. "
                        "I cannot provide a reliable answer."
                    ),
                    citations=[],
                    context=context,
                    usage=Usage(),
                    timings=_stage_timings(timer),
                )
        messages = build_messages(query, context, isolation=active.prompt_isolation)
        params = GenParams(
            temperature=self._config.generator.temperature,
            max_tokens=self._config.generator.max_tokens,
        )
        with timer.stage("generate"):
            generated = await self._generator.generate(messages, params=params)
        citations = parse_citations(generated.text, context)
        timings = _stage_timings(timer)
        return Answer(
            text=generated.text,
            citations=citations,
            context=context,
            usage=generated.usage,
            timings=timings,
        )


def _stage_timings(timer: StageTimer) -> StageTimings:
    return StageTimings(
        embed_query_ms=timer.get("embed_query") or 0.0,
        retrieve_ms=timer.get("retrieve") or 0.0,
        rerank_ms=timer.get("rerank"),
        generate_ms=timer.get("generate") or 0.0,
        total_ms=timer.total_ms(),
    )


def _conflict_abstention(conflicts: tuple[ClaimConflict, ...]) -> str:
    details = "; ".join(f"{conflict.unit}: {', '.join(conflict.values)}" for conflict in conflicts)
    return (
        f"The retrieved sources conflict ({details}). "
        "I cannot provide a reliable answer from the available evidence."
    )
