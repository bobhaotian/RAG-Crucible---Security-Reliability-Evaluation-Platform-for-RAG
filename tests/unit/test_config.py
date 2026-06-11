"""RunSpec validation, canonical serialization, and the committed spec files."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from crucible.config import (
    ChunkerConfig,
    CorpusConfig,
    DefensesConfig,
    GeneratorConfig,
    PipelineConfig,
    ProviderRef,
    RerankerConfig,
    RetrieverConfig,
    RunSpec,
    SpecError,
    load_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _minimal_spec_dict() -> dict[str, object]:
    return {
        "name": "minimal",
        "corpus": {"documents": "datasets/seeded/corpus"},
        "pipeline": {
            "embedder": {"provider": "fake", "model": "hash-64"},
            "reranker": {"provider": "fake", "model": "overlap"},
            "generator": {"provider": "fake", "model": "extractive"},
        },
    }


def test_minimal_spec_parses_with_defaults() -> None:
    spec = RunSpec.model_validate(_minimal_spec_dict())
    assert spec.seed == 42
    assert spec.ingest.chunker.type == "fixed"
    assert spec.index.store == "faiss"
    assert spec.pipeline.retriever.k == 20
    assert spec.suites is None


def test_unknown_keys_are_errors() -> None:
    raw = _minimal_spec_dict()
    raw["retreiver_typo"] = {"k": 5}
    with pytest.raises(ValidationError, match="retreiver_typo"):
        RunSpec.model_validate(raw)


def test_top_n_cannot_exceed_k() -> None:
    with pytest.raises(ValidationError, match="top_n"):
        PipelineConfig(
            embedder=ProviderRef(provider="fake", model="m"),
            retriever=RetrieverConfig(k=3),
            reranker=RerankerConfig(provider="fake", model="m", top_n=10),
            generator=GeneratorConfig(provider="fake", model="m"),
        )


def test_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        ChunkerConfig(size_tokens=100, overlap_tokens=100)


def test_defenses_rejected_until_phase_4() -> None:
    with pytest.raises(ValidationError, match="Phase 4"):
        DefensesConfig(prompt_isolation=True)


def test_canonical_json_is_stable_and_hash_tracks_content() -> None:
    a = RunSpec.model_validate(_minimal_spec_dict())
    b = RunSpec.model_validate(_minimal_spec_dict())
    assert a.canonical_json() == b.canonical_json()
    assert a.spec_hash() == b.spec_hash()
    c = RunSpec.model_validate({**_minimal_spec_dict(), "seed": 7})
    assert c.spec_hash() != a.spec_hash()


def test_ingest_fingerprint_tracks_index_shape_only() -> None:
    base = RunSpec.model_validate(_minimal_spec_dict())

    raw_gen = _minimal_spec_dict()
    pipeline = raw_gen["pipeline"]
    assert isinstance(pipeline, dict)
    pipeline["generator"] = {"provider": "fake", "model": "other", "temperature": 0.5}
    different_generator = RunSpec.model_validate(raw_gen)
    assert different_generator.ingest_fingerprint() == base.ingest_fingerprint()

    raw_chunk = _minimal_spec_dict()
    raw_chunk["ingest"] = {"chunker": {"size_tokens": 100}}
    different_chunker = RunSpec.model_validate(raw_chunk)
    assert different_chunker.ingest_fingerprint() != base.ingest_fingerprint()


def test_committed_specs_are_valid() -> None:
    for name in ("demo.yaml", "smoke-fake.yaml"):
        spec = load_spec(REPO_ROOT / "specs" / name)
        assert spec.corpus.documents == Path("datasets/seeded/corpus")


def test_load_spec_errors_name_the_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(SpecError, match=r"nope\.yaml"):
        load_spec(missing)
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(SpecError, match=r"bad\.yaml"):
        load_spec(bad)


def test_corpus_config_requires_documents() -> None:
    with pytest.raises(ValidationError):
        CorpusConfig()  # type: ignore[call-arg]


def _spec_with_suites(suites: dict[str, object]) -> dict[str, object]:
    raw = _minimal_spec_dict()
    raw["corpus"] = {"documents": "datasets/seeded/corpus", "qa": "datasets/seeded/qa.jsonl"}
    raw["suites"] = suites
    return raw


def test_llm_judge_requires_provider_model_and_cache() -> None:
    with pytest.raises(ValidationError, match=r"judge\.provider"):
        RunSpec.model_validate(_spec_with_suites({"faithfulness": {"judge": {"kind": "llm"}}}))
    with pytest.raises(ValidationError, match=r"judge\.cache"):
        RunSpec.model_validate(
            _spec_with_suites(
                {
                    "faithfulness": {
                        "judge": {"kind": "llm", "provider": "fake", "model": "m", "mode": "auto"}
                    }
                }
            )
        )


def test_k_values_cannot_exceed_retrieval_depth() -> None:
    with pytest.raises(ValidationError, match="retrieval depth"):
        RunSpec.model_validate(_spec_with_suites({"retrieval": {"k_values": [1, 50]}}))


def test_suites_require_qa_labels() -> None:
    raw = _minimal_spec_dict()
    raw["suites"] = {"retrieval": {}}
    with pytest.raises(ValidationError, match=r"corpus\.qa"):
        RunSpec.model_validate(raw)
