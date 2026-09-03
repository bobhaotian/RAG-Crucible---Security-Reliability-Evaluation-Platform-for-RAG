"""Data contracts owned by the pipeline (DESIGN.md §3)."""

from __future__ import annotations

from crucible.providers.base import Usage
from crucible.types import Chunk, StrictModel


class Candidate(StrictModel):
    chunk: Chunk
    score: float
    rank: int  # 0-based position in the current ordering


class RankedContext(StrictModel):
    candidates: list[Candidate]
    rerank_applied: bool


class Citation(StrictModel):
    """``parsed=True``: the generator emitted this marker and it maps to a
    context passage. ``parsed=False``: marker-level parsing found nothing, so
    this is context-level fallback (the chunk was in the prompt). The
    faithfulness suite scores the two levels separately."""

    chunk_id: str
    marker: int  # 1-based index into the context block list
    parsed: bool


class StageTimings(StrictModel):
    embed_query_ms: float
    retrieve_ms: float
    rerank_ms: float | None  # None when the rerank stage is disabled
    generate_ms: float
    total_ms: float


class Answer(StrictModel):
    text: str
    citations: list[Citation]
    context: RankedContext
    usage: Usage
    timings: StageTimings
    abstained: bool = False
    abstention_reason: str | None = None
