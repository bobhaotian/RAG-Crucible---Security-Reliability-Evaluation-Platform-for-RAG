from __future__ import annotations

import pytest

from crucible.attacks import generate_injection_attacks, generate_poison_attacks
from crucible.config import DefenseName, SecuritySuiteConfig
from crucible.eval.security import _aggregate, _defenses_for, _markers_present
from crucible.eval.types import AttackRecord, MarkerRef
from crucible.qa import QAItem


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
    (
        "condition",
        "prompt_isolation",
        "injection_filter",
        "answer_integrity",
    ),
    [
        ("none", False, False, False),
        ("prompt_isolation", True, False, False),
        ("injection_filter", False, True, False),
        ("answer_integrity", False, False, True),
    ],
)
def test_defenses_for_enables_only_the_selected_condition(
    condition: DefenseName,
    prompt_isolation: bool,
    injection_filter: bool,
    answer_integrity: bool,
) -> None:
    defenses = _defenses_for(condition)
    assert defenses.prompt_isolation is prompt_isolation
    assert defenses.injection_filter is injection_filter
    assert defenses.answer_integrity is answer_integrity


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


MARKERS = (
    MarkerRef(marker="900000", attack_type="poison", qid="q1"),
    MarkerRef(marker="900001", attack_type="poison", qid="q2"),
    MarkerRef(marker="OWNED-q1", attack_type="injection", qid="q1"),
)


def test_markers_present_finds_only_planted_markers_and_keeps_their_owner() -> None:
    found = _markers_present("the value is 900001 USD", MARKERS)
    assert [(m.marker, m.attack_type, m.qid) for m in found] == [("900001", "poison", "q2")]
    assert [m.marker for m in _markers_present("OWNED-q1", MARKERS)] == ["OWNED-q1"]
    # 900001 must not match the 900000 sentinel: the check is exact containment.
    assert "900000" not in [m.marker for m in _markers_present("900001", MARKERS)]
    assert _markers_present("14 hours", MARKERS) == ()


def test_record_classifies_markers_by_owner() -> None:
    """The three buckets a reader needs to tell apart."""
    record = _attack(
        qid="q1",
        own_marker="900000",
        compromised=True,
        matched_markers=(MARKERS[2], MARKERS[1]),  # OWNED-q1 (same q), 900001 (other q)
    )
    assert [m.marker for m in record.foreign_markers] == ["OWNED-q1", "900001"]
    assert [m.marker for m in record.competing_markers] == ["OWNED-q1"]
    assert [m.marker for m in record.cross_question_markers] == ["900001"]


def test_compromise_rate_counts_trials_the_per_attack_rate_misses() -> None:
    """A poison trial hijacked by a co-resident injection document.

    `succeeded` is False — the poison sentinel never appeared — but the model
    emitted attacker-controlled text, so knowledge_corruption_rate alone
    understates how often the pipeline was compromised.
    """
    config = SecuritySuiteConfig(defenses=("none",))
    records = [
        _attack(
            qid="q1",
            succeeded=True,
            own_marker="900000",
            compromised=True,
            matched_markers=(MarkerRef(marker="900000", attack_type="poison", qid="q1"),),
            answer="900000 hours",
        ),
        _attack(
            qid="q2",
            succeeded=False,
            own_marker="900001",
            compromised=True,
            matched_markers=(MarkerRef(marker="OWNED-q2", attack_type="injection", qid="q2"),),
            answer="OWNED-q2",
        ),
        _attack(qid="q3", succeeded=False, own_marker="900002", answer="14 hours"),
        _attack(qid="q4", succeeded=False, own_marker="900003", answer="14 hours"),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("knowledge_corruption_rate", "defense=none")] == 0.25
    # same denominator, so the gap is exactly what per-attack attribution misses
    assert metrics[("poison_compromise_rate", "defense=none")] == 0.5
    # q2 was beaten by the injection on its own question, not by another question
    assert metrics[("attack_competition_rate", "defense=none")] == 0.25
    assert metrics[("cross_question_contamination_rate", "defense=none")] == 0.0


def test_a_marker_from_another_question_is_contamination_not_competition() -> None:
    """The alarming case: an attack document escaped the question it targets."""
    config = SecuritySuiteConfig(defenses=("none",))
    records = [
        _attack(
            qid="q1",
            succeeded=False,
            own_marker="900000",
            compromised=True,
            matched_markers=(MarkerRef(marker="900009", attack_type="poison", qid="q9"),),
            answer="900009 hours",
        ),
        _attack(qid="q2", succeeded=False, own_marker="900001", answer="14 hours"),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("poison_compromise_rate", "defense=none")] == 0.5
    assert metrics[("attack_competition_rate", "defense=none")] == 0.0
    assert metrics[("cross_question_contamination_rate", "defense=none")] == 0.5


def _qa(n: int) -> list[QAItem]:
    return [
        QAItem(
            qid=f"q{i:03d}",
            question=f"question {i}?",
            answer=f"{i} hours",
            gold_fact=f"Fact {i} is {i} hours.",
        )
        for i in range(n)
    ]


def test_targets_overlap_by_default_because_both_draw_from_the_whole_pool() -> None:
    items = _qa(20)
    poison = generate_poison_attacks(items, 10, 11)
    injections = generate_injection_attacks(items, 10, 13)

    # Not asserting a specific overlap — only that nothing prevents one, which is
    # the property `disjoint_targets` exists to change.
    assert {a.qid for a in poison} & {a.qid for a in injections}


def test_disjoint_targets_partitions_the_pool_so_no_question_carries_both() -> None:
    items = _qa(20)
    poison = generate_poison_attacks(items, 10, 11)
    remaining = [item for item in items if item.qid not in {a.qid for a in poison}]
    injections = generate_injection_attacks(remaining, 10, 13)

    assert not ({a.qid for a in poison} & {a.qid for a in injections})
    assert len(injections) == 10


def test_disjoint_targets_yields_fewer_injections_when_the_remainder_is_small() -> None:
    """select_targets returns the whole pool when asked for more than it holds."""
    items = _qa(12)
    poison = generate_poison_attacks(items, 10, 11)
    remaining = [item for item in items if item.qid not in {a.qid for a in poison}]
    injections = generate_injection_attacks(remaining, 10, 13)

    assert len(injections) == 2
    assert not ({a.qid for a in poison} & {a.qid for a in injections})
