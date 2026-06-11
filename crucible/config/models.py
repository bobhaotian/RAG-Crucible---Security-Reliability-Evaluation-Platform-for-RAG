"""The RunSpec: one YAML document fully describes an evaluation run.

Design rules (DESIGN.md §5):

- unknown keys are errors everywhere (``extra="forbid"``) — a typo'd option
  must never silently become a default;
- cross-field invariants validate at parse time, not mid-run;
- the canonical-JSON serialization (and its sha256) is what gets persisted
  with results, so a run is reproducible from the stored spec alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderName = Literal["local", "cohere", "openai", "fake"]
FilterName = Literal["dedup", "language", "boilerplate"]


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderRef(StrictConfig):
    """Points one pipeline stage at one provider implementation."""

    provider: ProviderName
    model: str


class ChunkerConfig(StrictConfig):
    type: Literal["fixed", "structure"] = "fixed"
    size_tokens: int = Field(default=350, ge=20)
    overlap_tokens: int = Field(default=60, ge=0)

    @model_validator(mode="after")
    def _overlap_within_size(self) -> ChunkerConfig:
        if self.overlap_tokens >= self.size_tokens:
            raise ValueError("chunker.overlap_tokens must be smaller than size_tokens")
        return self


class CorpusConfig(StrictConfig):
    documents: Path
    qa: Path | None = None


class IngestConfig(StrictConfig):
    filters: tuple[FilterName, ...] = ("dedup", "language", "boilerplate")
    chunker: ChunkerConfig = ChunkerConfig()


class IndexConfig(StrictConfig):
    store: Literal["faiss", "qdrant"] = "faiss"
    metric: Literal["cosine"] = "cosine"


class RetrieverConfig(StrictConfig):
    k: int = Field(default=20, ge=1)


class RerankerConfig(ProviderRef):
    """Reranking stage. ``enabled: false`` keeps the stage configured but
    inactive — the retrieval suite flips this toggle to measure rerank lift."""

    enabled: bool = True
    top_n: int = Field(default=5, ge=1)


class GeneratorConfig(ProviderRef):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1)


class DefensesConfig(StrictConfig):
    """Security-suite defense toggles. Implementations land in Phase 4; until
    then enabling one is a config error rather than a silent no-op."""

    prompt_isolation: bool = False
    injection_filter: bool = False

    @model_validator(mode="after")
    def _not_implemented_yet(self) -> DefensesConfig:
        if self.prompt_isolation or self.injection_filter:
            raise ValueError("defenses ship in Phase 4; toggles must be false for now")
        return self


class PipelineConfig(StrictConfig):
    embedder: ProviderRef
    retriever: RetrieverConfig = RetrieverConfig()
    reranker: RerankerConfig
    generator: GeneratorConfig
    defenses: DefensesConfig = DefensesConfig()

    @model_validator(mode="after")
    def _top_n_within_k(self) -> PipelineConfig:
        if self.reranker.top_n > self.retriever.k:
            raise ValueError(
                f"reranker.top_n ({self.reranker.top_n}) cannot exceed "
                f"retriever.k ({self.retriever.k})"
            )
        return self


class SuitesConfig(StrictConfig):
    """Evaluation suite selection. Suites land in Phase 2+; the key exists now
    so spec files stay stable as suites are added."""


class RunSpec(StrictConfig):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    seed: int = 42
    corpus: CorpusConfig
    ingest: IngestConfig = IngestConfig()
    index: IndexConfig = IndexConfig()
    pipeline: PipelineConfig
    suites: SuitesConfig | None = None

    def canonical_json(self) -> str:
        """Stable serialization: key-sorted, no whitespace. This exact string
        (and its hash) is persisted with results."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def spec_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def ingest_fingerprint(self) -> str:
        """Hash of everything that shapes the index (corpus, filters, chunker,
        store, embedder). A saved index records this; querying with a spec
        whose fingerprint differs means the index is stale."""
        parts = {
            "corpus": self.corpus.model_dump(mode="json"),
            "ingest": self.ingest.model_dump(mode="json"),
            "index": self.index.model_dump(mode="json"),
            "embedder": self.pipeline.embedder.model_dump(mode="json"),
        }
        blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()
