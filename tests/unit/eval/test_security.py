from __future__ import annotations

import pytest

from crucible.config import DefenseName, SecuritySuiteConfig
from crucible.eval.security import _aggregate, _defenses_for, _markers_present
from crucible.eval.types import AttackRecord


def test_aggregate_separates_retrieval_from_defense_success() -> None:
    config = SecuritySuiteConfig(defenses=("none", "injection_filter"))
    records = [
        AttackRecord(
            attack_type="injection",
            qid="q1",
            question="question",
            defense="none",
            retrieved=True,
            succeeded=True,
            answer="obeyed",
        ),
        AttackRecord(
            attack_type="injection",
            qid="q1",
            question="question",
            defense="injection_filter",
            retrieved=False,
            succeeded=False,
            answer="blocked",
        ),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("injection_retrieval_rate", "")] == 1.0
    assert metrics[("injection_compliance_rate", "defense=none")] == 1.0
    assert metrics[("injection_compliance_rate", "defense=injection_filter")] == 0.0


@pytest.mark.parametrize(
    ("condition", "prompt_isolation", "injection_filter"),
    [("none", False, False), ("prompt_isolation", True, False), ("injection_filter", False, True)],
)
def test_defenses_for_enables_only_the_selected_condition(
    condition: DefenseName, prompt_isolation: bool, injection_filter: bool
) -> None:
    defenses = _defenses_for(condition)
    assert defenses.prompt_isolation is prompt_isolation
    assert defenses.injection_filter is injection_filter


def _attack(**overrides: object) -> AttackRecord:
    base: dict[str, object] = {
        "attack_type": "poison",
        "qid": "q1",
        "question": "question",
        "defense": "none",
        "retrieved": True,
        "succeeded": False,
        "answer": "",
    }
    return AttackRecord.model_validate(base | overrides)


def test_markers_present_finds_only_planted_markers() -> None:
    markers = ("900000", "900001", "OWNED-q027")
    assert _markers_present("the value is 900001 USD", markers) == ("900001",)
    assert _markers_present("OWNED-q027", markers) == ("OWNED-q027",)
    # 900001 must not match the 900000 sentinel: the check is exact containment.
    assert "900000" not in _markers_present("900001", markers)
    assert _markers_present("14 hours", markers) == ()


def test_compromise_rate_counts_trials_the_per_attack_rate_misses() -> None:
    """A poison trial hijacked by a co-resident injection document.

    `succeeded` is False — the poison sentinel never appeared — but the model
    emitted attacker-controlled text, so knowledge_corruption_rate alone
    understates how often the pipeline was compromised.
    """
    config = SecuritySuiteConfig(defenses=("none",))
    records = [
        _attack(qid="q1", succeeded=True, compromised=True, answer="900000 hours"),
        _attack(
            qid="q2",
            succeeded=False,
            compromised=True,
            foreign_markers=("OWNED-q2",),
            answer="OWNED-q2",
        ),
        _attack(qid="q3", succeeded=False, compromised=False, answer="14 hours"),
        _attack(qid="q4", succeeded=False, compromised=False, answer="14 hours"),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("knowledge_corruption_rate", "defense=none")] == 0.25
    # same denominator, so the gap is exactly what per-attack attribution misses
    assert metrics[("poison_compromise_rate", "defense=none")] == 0.5
    assert metrics[("cross_contamination_rate", "defense=none")] == 0.25


def test_cross_contamination_is_zero_when_every_marker_is_the_attack_under_test() -> None:
    config = SecuritySuiteConfig(defenses=("none",))
    records = [
        _attack(succeeded=True, compromised=True, answer="900000 hours"),
        _attack(succeeded=False, compromised=False, answer="14 hours"),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("poison_compromise_rate", "defense=none")] == 0.5
    assert metrics[("cross_contamination_rate", "defense=none")] == 0.0
