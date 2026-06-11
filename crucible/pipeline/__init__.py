"""The configurable RAG pipeline: retrieve → rerank → generate."""

from crucible.pipeline.citations import parse_citations
from crucible.pipeline.factory import build_pipeline
from crucible.pipeline.prompts import TEMPLATE_VERSION, build_messages
from crucible.pipeline.rag import RagPipeline
from crucible.pipeline.types import (
    Answer,
    Candidate,
    Citation,
    RankedContext,
    StageTimings,
)

__all__ = [
    "TEMPLATE_VERSION",
    "Answer",
    "Candidate",
    "Citation",
    "RagPipeline",
    "RankedContext",
    "StageTimings",
    "build_messages",
    "build_pipeline",
    "parse_citations",
]
