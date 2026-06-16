"""Privacy suite configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crucible.config import RunSpec


def _spec(privacy: dict[str, object], *, qa: bool = False) -> dict[str, object]:
    corpus: dict[str, object] = {"documents": "datasets/seeded/corpus"}
    if qa:
        corpus["qa"] = "datasets/seeded/qa.jsonl"
    return {
        "name": "priv",
        "corpus": corpus,
        "pipeline": {
            "embedder": {"provider": "fake", "model": "hash-64"},
            "reranker": {"provider": "fake", "model": "overlap"},
            "generator": {"provider": "fake", "model": "extractive"},
        },
        "suites": {"privacy": privacy},
    }


def test_privacy_only_run_does_not_require_qa() -> None:
    spec = RunSpec.model_validate(_spec({}))  # no corpus.qa
    assert spec.suites is not None and spec.suites.privacy is not None
    assert spec.suites.privacy.defenses == ("none", "pii_filter")


def test_security_still_requires_qa_even_alongside_privacy() -> None:
    raw = _spec({})
    raw["suites"] = {"privacy": {}, "security": {}}  # security needs qa
    with pytest.raises(ValidationError, match=r"require corpus\.qa"):
        RunSpec.model_validate(raw)


def test_empty_probe_or_kind_lists_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        RunSpec.model_validate(_spec({"probes": []}))
    with pytest.raises(ValidationError, match="non-empty"):
        RunSpec.model_validate(_spec({"kinds": []}))


def test_unknown_canary_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        RunSpec.model_validate(_spec({"kinds": ["ssn"]}))


def test_pii_is_a_valid_ingest_filter() -> None:
    raw = _spec({}, qa=False)
    raw["ingest"] = {"filters": ["dedup", "pii"]}
    spec = RunSpec.model_validate(raw)
    assert "pii" in spec.ingest.filters
