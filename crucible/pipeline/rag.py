"""The RAG pipeline — the system under test.

retrieve → (rerank) → generate, with citations and per-stage timing on every
answer. Eval suites consume this class only through ``answer`` / ``retrieve``;
they never reach into provider or index internals.
"""

from __future__ import annotations

from crucible.config import PipelineConfig
from crucible.index import VectorIndex
from crucible.obs import StageTimer
from crucible.pipeline.citations import parse_citations
from crucible.pipeline.prompts import build_messages
from crucible.pipeline.types import Answer, Candidate, RankedContext, StageTimings
from crucible.providers import (
    Embedder,
    EmbedInputType,
    Generator,
    GenParams,
    Reranker,
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
            timer = timer or StageTimer()
            with timer.stage("rerank"):
                result = await self._reranker.rerank(
                    query, [c.chunk.text for c in candidates], top_n=top_n
                )
            reordered = [
                Candidate(chunk=candidates[item.index].chunk, score=item.score, rank=rank)
                for rank, item in enumerate(result.ranking)
            ]
            return RankedContext(candidates=reordered, rerank_applied=True)
        return RankedContext(candidates=candidates[:top_n], rerank_applied=False)

    async def answer(self, query: str) -> Answer:
        timer = StageTimer()
        candidates = await self.retrieve(query, timer=timer)
        context = await self.build_context(query, candidates, timer=timer)
        messages = build_messages(query, context)
        params = GenParams(
            temperature=self._config.generator.temperature,
            max_tokens=self._config.generator.max_tokens,
        )
        with timer.stage("generate"):
            generated = await self._generator.generate(messages, params=params)
        citations = parse_citations(generated.text, context)
        timings = StageTimings(
            embed_query_ms=timer.get("embed_query") or 0.0,
            retrieve_ms=timer.get("retrieve") or 0.0,
            rerank_ms=timer.get("rerank"),
            generate_ms=timer.get("generate") or 0.0,
            total_ms=timer.total_ms(),
        )
        return Answer(
            text=generated.text,
            citations=citations,
            context=context,
            usage=generated.usage,
            timings=timings,
        )
