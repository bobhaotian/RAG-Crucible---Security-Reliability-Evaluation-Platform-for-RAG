"""Attack generators: determinism, retrievability shape, detectable targets."""

from __future__ import annotations

from crucible.attacks import (
    INJECT_SOURCE_PREFIX,
    POISON_SOURCE_PREFIX,
    generate_injection_attacks,
    generate_poison_attacks,
    select_targets,
)
from crucible.qa import QAItem

ITEMS = [
    QAItem(
        qid=f"q{i:03d}",
        question=f"What is the spec value number {i}?",
        answer=f"{i * 10} units",
        gold_fact=f"The spec value number {i} is {i * 10} units.",
    )
    for i in range(1, 9)
]


def test_select_targets_is_deterministic_and_sorted() -> None:
    a = select_targets(ITEMS, 4, seed=42)
    b = select_targets(ITEMS, 4, seed=42)
    assert [i.qid for i in a] == [i.qid for i in b]
    assert [i.qid for i in a] == sorted(i.qid for i in a)
    assert select_targets(ITEMS, None, seed=1) == sorted(ITEMS, key=lambda i: i.qid)
    assert len(select_targets(ITEMS, 100, seed=1)) == len(ITEMS)


def test_poison_doc_is_false_retrievable_and_detectable() -> None:
    attacks = generate_poison_attacks(ITEMS, n=3, seed=7)
    assert len(attacks) == 3
    for attack in attacks:
        item = next(i for i in ITEMS if i.qid == attack.qid)
        text = attack.document.text
        # the false sentinel is present; the true answer is gone
        assert attack.target_value in text
        assert item.answer not in text
        # echoes the question wording so it competes for retrieval
        assert item.question.rstrip("? ") in text
        assert attack.document.source.startswith(POISON_SOURCE_PREFIX)


def test_poison_is_deterministic() -> None:
    first = generate_poison_attacks(ITEMS, n=4, seed=7)
    second = generate_poison_attacks(ITEMS, n=4, seed=7)
    assert [(a.qid, a.target_value, a.document.doc_id) for a in first] == [
        (a.qid, a.target_value, a.document.doc_id) for a in second
    ]


def test_injection_doc_carries_token_and_rotates_templates() -> None:
    attacks = generate_injection_attacks(ITEMS, n=6, seed=3)
    assert len(attacks) == 6
    for attack in attacks:
        assert attack.token == f"OWNED-{attack.qid}"
        assert attack.token in attack.document.text
        assert attack.question in attack.document.text  # retrievable
        assert attack.document.source.startswith(INJECT_SOURCE_PREFIX)
    assert {a.template for a in attacks} == {"ignore_previous", "exfil_token"}


def test_injection_payloads_trip_the_filter() -> None:
    from crucible.pipeline import looks_like_injection

    for attack in generate_injection_attacks(ITEMS, n=6, seed=3):
        assert looks_like_injection(attack.document.text)
