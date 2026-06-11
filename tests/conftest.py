"""Shared fixtures: a tiny deterministic corpus + fake-provider specs."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.config import (
    ChunkerConfig,
    CorpusConfig,
    GeneratorConfig,
    IngestConfig,
    PipelineConfig,
    ProviderRef,
    RerankerConfig,
    RetrieverConfig,
    RunSpec,
)

TINY_DOCS = {
    "products/widget-spec.md": (
        "# Widget X1 specification\n\n"
        "The Widget X1 is a compact industrial sensor for vibration monitoring.\n\n"
        "## Specifications\n\n"
        "The X1 has a battery life of 72 hours. The X1 weighs 250 grams.\n"
        "The X1 transmits readings over LoRaWAN every thirty seconds.\n"
    ),
    "products/gadget-spec.md": (
        "# Gadget Z9 specification\n\n"
        "The Gadget Z9 is a handheld thermal camera for electrical inspections.\n\n"
        "## Specifications\n\n"
        "The Z9 has a battery life of 9 hours. The Z9 stores 4000 images.\n"
        "The Z9 resolves temperature differences of 0.05 degrees.\n"
    ),
    "handbook/returns.txt": (
        "Returns policy\n\n"
        "Customers may return any product within 45 days of delivery.\n"
        "Refunds are issued to the original payment method within one week.\n"
    ),
}


@pytest.fixture
def tiny_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for relpath, text in TINY_DOCS.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def make_fake_spec(
    corpus_dir: Path,
    *,
    name: str = "test-fake",
    rerank_enabled: bool = True,
    chunker: ChunkerConfig | None = None,
) -> RunSpec:
    return RunSpec(
        name=name,
        seed=42,
        corpus=CorpusConfig(documents=corpus_dir),
        ingest=IngestConfig(chunker=chunker or ChunkerConfig(size_tokens=80, overlap_tokens=20)),
        pipeline=PipelineConfig(
            embedder=ProviderRef(provider="fake", model="hash-64"),
            retriever=RetrieverConfig(k=8),
            reranker=RerankerConfig(
                provider="fake", model="overlap", enabled=rerank_enabled, top_n=3
            ),
            generator=GeneratorConfig(provider="fake", model="extractive"),
        ),
    )
