from __future__ import annotations

import pytest

from crucible.config import DefenseName, SecuritySuiteConfig
from crucible.eval.security import _aggregate, _defenses_for
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
