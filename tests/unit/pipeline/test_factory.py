from __future__ import annotations

from crucible.index import FaissIndex
from crucible.pipeline import RagPipeline, build_pipeline
from crucible.providers.fake import FakeEmbedder, FakeGenerator, FakeReranker

from ...conftest import make_fake_spec


def test_build_pipeline_constructs_configured_fake_providers(tmp_path) -> None:
    spec = make_fake_spec(tmp_path)

    pipeline = build_pipeline(spec, FaissIndex(64))

    assert isinstance(pipeline, RagPipeline)
    assert isinstance(pipeline.embedder, FakeEmbedder)
    assert pipeline.has_reranker is True
    assert isinstance(pipeline._reranker, FakeReranker)
    assert isinstance(pipeline._generator, FakeGenerator)
