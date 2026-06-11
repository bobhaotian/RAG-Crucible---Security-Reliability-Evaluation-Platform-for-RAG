"""Assemble a RagPipeline from a RunSpec and a loaded index."""

from __future__ import annotations

from crucible.config import RunSpec
from crucible.index import VectorIndex
from crucible.pipeline.rag import RagPipeline
from crucible.providers import build_embedder, build_generator, build_reranker


def build_pipeline(spec: RunSpec, index: VectorIndex) -> RagPipeline:
    """Build all providers named by the spec. Capability and dependency
    problems surface here (build time), not mid-query.

    The reranker is built even when ``enabled: false``: the toggle gates the
    answer path, while the retrieval suite still needs the stage to measure
    rerank lift. Local models load lazily, so an unused reranker costs nothing.
    """
    return RagPipeline(
        config=spec.pipeline,
        embedder=build_embedder(spec.pipeline.embedder),
        index=index,
        reranker=build_reranker(spec.pipeline.reranker),
        generator=build_generator(spec.pipeline.generator),
    )
