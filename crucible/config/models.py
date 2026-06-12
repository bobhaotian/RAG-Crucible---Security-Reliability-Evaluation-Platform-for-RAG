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


class RetrievalSuiteConfig(StrictConfig):
    k_values: tuple[int, ...] = (1, 5, 10, 20)
    rerank_lift: bool = True  # also evaluate with rerank off and report the delta

    @model_validator(mode="after")
    def _k_values_sane(self) -> RetrievalSuiteConfig:
        if not self.k_values or any(k < 1 for k in self.k_values):
            raise ValueError("retrieval.k_values must be non-empty positive integers")
        return self


class JudgeConfig(StrictConfig):
    """Entailment judge for the faithfulness suite.

    ``llm`` judges through the provider interface; ``heuristic`` is a
    deterministic token-containment scorer (no model — what CI uses). Cache
    modes: ``auto`` reads the cache and judges+persists misses, ``cached`` is
    read-only (miss = error, full reproducibility), ``live`` always re-judges
    and refreshes entries.
    """

    kind: Literal["llm", "heuristic"] = "llm"
    provider: ProviderName | None = None
    model: str | None = None
    mode: Literal["auto", "cached", "live"] = "auto"
    cache: Path | None = None

    @model_validator(mode="after")
    def _llm_requirements(self) -> JudgeConfig:
        if self.kind == "llm":
            if self.provider is None or self.model is None:
                raise ValueError("judge.kind=llm requires judge.provider and judge.model")
            if self.mode in ("auto", "cached") and self.cache is None:
                raise ValueError(f"judge.mode={self.mode} requires a judge.cache path")
        return self


class FaithfulnessSuiteConfig(StrictConfig):
    judge: JudgeConfig
    sample_size: int | None = Field(default=None, ge=1)  # None = all QA items


class SuitesConfig(StrictConfig):
    """Evaluation suite selection. Security and privacy suites are added here
    in Phases 4-5."""

    retrieval: RetrievalSuiteConfig | None = None
    faithfulness: FaithfulnessSuiteConfig | None = None
    # Bounded parallelism for suite items. Default 1: the shipped local
    # providers are CPU-bound, where concurrency only inflates per-call wall
    # times. Raise it for I/O-bound hosted providers (cohere/openai).
    concurrency: int = Field(default=1, ge=1)


class RunSpec(StrictConfig):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    seed: int = 42
    corpus: CorpusConfig
    ingest: IngestConfig = IngestConfig()
    index: IndexConfig = IndexConfig()
    pipeline: PipelineConfig
    suites: SuitesConfig | None = None

    @model_validator(mode="after")
    def _suites_consistent(self) -> RunSpec:
        if self.suites is None:
            return self
        if (self.suites.retrieval or self.suites.faithfulness) and self.corpus.qa is None:
            raise ValueError("evaluation suites require corpus.qa (the labeled QA file)")
        if self.suites.retrieval is not None:
            k_max = max(self.suites.retrieval.k_values)
            if k_max > self.pipeline.retriever.k:
                raise ValueError(
                    f"retrieval.k_values includes {k_max} but retriever.k is "
                    f"{self.pipeline.retriever.k}; metrics@k cannot exceed retrieval depth"
                )
        return self

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
