"""The committed seeded corpus must keep the invariants the eval suites
(Phase 2+) build on: noise docs hit their filters, every gold fact survives
loading + filtering, and every gold fact lands inside at least one chunk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crucible.config import load_spec
from crucible.ingest import apply_filters, chunk_document, load_corpus
from crucible.types import Document

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDED = REPO_ROOT / "datasets" / "seeded"


@pytest.fixture(scope="module")
def filtered_docs() -> list[Document]:
    docs, _ = load_corpus(SEEDED / "corpus")
    kept, _ = apply_filters(docs, ["dedup", "language", "boilerplate"])
    return kept


@pytest.fixture(scope="module")
def qa_pairs() -> list[dict[str, str]]:
    lines = (SEEDED / "qa.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_corpus_loads_and_filters_drop_exactly_the_noise() -> None:
    docs, skipped = load_corpus(SEEDED / "corpus")
    assert skipped == []
    assert len(docs) == 35

    kept, stats = apply_filters(docs, ["dedup", "language", "boilerplate"])
    dropped = {s.name: s.dropped for s in stats}
    assert dropped == {"dedup": 1, "language": 1, "boilerplate": 1}
    sources = {d.source for d in kept}
    assert "noise/duplicate-vacation.md" not in sources
    assert "noise/communique-fr.txt" not in sources
    assert "noise/promo.html" not in sources
    assert "handbook/vacation.md" in sources  # the original survives the dedup


def test_every_gold_fact_survives_into_its_document(
    filtered_docs: list[Document], qa_pairs: list[dict[str, str]]
) -> None:
    assert len(qa_pairs) == 56
    by_source = {d.source: d for d in filtered_docs}
    for pair in qa_pairs:
        doc = by_source[pair["gold_doc"]]
        assert pair["gold_fact"] in doc.text, f"{pair['qid']}: fact missing in {doc.source}"


def test_every_gold_fact_is_contained_in_a_chunk(
    filtered_docs: list[Document], qa_pairs: list[dict[str, str]]
) -> None:
    """The invariant retrieval metrics depend on: with the demo chunker, each
    gold fact appears whole in at least one chunk."""
    spec = load_spec(REPO_ROOT / "specs" / "demo.yaml")
    chunks_by_source: dict[str, list[str]] = {}
    for doc in filtered_docs:
        chunks_by_source[doc.source] = [c.text for c in chunk_document(doc, spec.ingest.chunker)]
    for pair in qa_pairs:
        texts = chunks_by_source[pair["gold_doc"]]
        assert any(pair["gold_fact"] in t for t in texts), (
            f"{pair['qid']}: gold fact split across chunk boundaries"
        )
