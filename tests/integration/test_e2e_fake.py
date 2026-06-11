"""End-to-end on the fake provider: ingest → index → retrieve → rerank →
generate → citations, fully deterministic."""

from __future__ import annotations

from pathlib import Path

from crucible.index import FaissIndex
from crucible.ingest import build_index
from crucible.pipeline import build_pipeline

from ..conftest import make_fake_spec


async def test_full_spine_answers_with_citations(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = make_fake_spec(tiny_corpus)
    out = tmp_path / "index"
    report = await build_index(spec, out)
    assert report.docs_indexed == 3
    assert report.chunks >= 3
    assert (out / "meta.json").is_file()

    index, meta = FaissIndex.load(out)
    assert meta.fingerprint == spec.ingest_fingerprint()

    pipeline = build_pipeline(spec, index)
    answer = await pipeline.answer("What is the battery life of the Widget X1?")

    assert answer.text and answer.text != "I don't know."
    assert "72 hours" in answer.text
    assert answer.citations, "answer must carry citations"
    context_ids = {c.chunk.chunk_id for c in answer.context.candidates}
    assert all(c.chunk_id in context_ids for c in answer.citations)
    assert answer.context.rerank_applied
    assert len(answer.context.candidates) <= spec.pipeline.reranker.top_n

    t = answer.timings
    assert t.total_ms > 0
    assert t.rerank_ms is not None
    assert answer.usage.input_tokens > 0


async def test_answers_are_deterministic(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = make_fake_spec(tiny_corpus)
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    pipeline = build_pipeline(spec, index)

    first = await pipeline.answer("How many days do customers have to return a product?")
    second = await pipeline.answer("How many days do customers have to return a product?")
    assert first.text == second.text
    assert [c.chunk_id for c in first.citations] == [c.chunk_id for c in second.citations]
    assert "45 days" in first.text


async def test_rerank_toggle_off(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = make_fake_spec(tiny_corpus, rerank_enabled=False)
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    pipeline = build_pipeline(spec, index)

    answer = await pipeline.answer("What is the battery life of the Widget X1?")
    assert not answer.context.rerank_applied
    assert answer.timings.rerank_ms is None
    assert len(answer.context.candidates) <= spec.pipeline.reranker.top_n
