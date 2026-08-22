"""Security suite configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crucible.config import RunSpec


def _spec(security: dict[str, object]) -> dict[str, object]:
    return {
        "name": "sec",
        "corpus": {"documents": "datasets/seeded/corpus", "qa": "datasets/seeded/qa.jsonl"},
        "pipeline": {
            "embedder": {"provider": "fake", "model": "hash-64"},
            "reranker": {"provider": "fake", "model": "overlap"},
            "generator": {"provider": "fake", "model": "extractive"},
        },
        "suites": {"security": security},
    }


def test_default_security_config_is_valid() -> None:
    spec = RunSpec.model_validate(_spec({}))
    assert spec.suites is not None and spec.suites.security is not None
    assert spec.suites.security.defenses == ("none", "prompt_isolation", "injection_filter")


def test_security_requires_an_enabled_attack() -> None:
    with pytest.raises(ValidationError, match="at least one of poisoning/injection"):
        RunSpec.model_validate(
            _spec({"poisoning": {"enabled": False}, "injection": {"enabled": False}})
        )


def test_security_requires_a_defense_condition() -> None:
    with pytest.raises(ValidationError, match="at least one condition"):
        RunSpec.model_validate(_spec({"defenses": []}))


def test_security_suite_requires_qa() -> None:
    raw = _spec({})
    raw["corpus"] = {"documents": "datasets/seeded/corpus"}  # no qa
    with pytest.raises(ValidationError, match=r"corpus\.qa"):
        RunSpec.model_validate(raw)


def test_unknown_defense_name_rejected() -> None:
    with pytest.raises(ValidationError):
        RunSpec.model_validate(_spec({"defenses": ["nope"]}))
