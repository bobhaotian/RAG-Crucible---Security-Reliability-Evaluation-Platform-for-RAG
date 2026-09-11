"""The configurable RAG pipeline: retrieve → rerank → generate."""

from rag_crucible.pipeline.citations import parse_citations
from rag_crucible.pipeline.consistency import (
    ClaimConflict,
    ConsistencyDecision,
    NumericClaim,
    extract_numeric_claims,
    find_numeric_conflicts,
    resolve_numeric_conflicts,
)
from rag_crucible.pipeline.defenses import (
    filter_injected_chunks,
    filter_untrusted_chunks,
    looks_like_injection,
)
from rag_crucible.pipeline.factory import build_pipeline
from rag_crucible.pipeline.prompts import TEMPLATE_VERSION, build_messages
from rag_crucible.pipeline.rag import RagPipeline
from rag_crucible.pipeline.types import (
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
    "ClaimConflict",
    "ConsistencyDecision",
    "NumericClaim",
    "RagPipeline",
    "RankedContext",
    "StageTimings",
    "build_messages",
    "build_pipeline",
    "extract_numeric_claims",
    "filter_injected_chunks",
    "filter_untrusted_chunks",
    "find_numeric_conflicts",
    "looks_like_injection",
    "parse_citations",
    "resolve_numeric_conflicts",
]
