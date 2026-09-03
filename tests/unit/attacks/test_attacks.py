"""Attack generators: determinism, retrievability shape, detectable targets."""

from __future__ import annotations

import re

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
    # Families alternate, so a small target count still samples both.
    assert {a.family for a in attacks} == {"seen", "heldout"}
    assert len([a for a in attacks if a.family == "seen"]) == 3


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def test_no_defense_pattern_reproduces_a_phrase_from_the_attack_set() -> None:
    """A defense may not be written by copying phrases out of the test set.

    Shared vocabulary is unavoidable — both sides talk about instructions and
    answers. Reproducing a *phrase* is not: it means the pattern was authored by
    reading the payload rather than the threat model.
    """
    from crucible.attacks.injection import _PAYLOADS
    from crucible.pipeline.defenses import _INJECTION_PATTERNS

    payload_trigrams = set()
    for text in _PAYLOADS.values():
        words = _words(text)
        payload_trigrams |= {tuple(words[i : i + 3]) for i in range(len(words) - 2)}

    for pattern in _INJECTION_PATTERNS:
        literal = re.sub(r"\\s\+|\\b|[()?|\\]|\{[^}]*\}", " ", pattern.pattern)
        words = _words(literal)
        quoted = [
            tuple(words[i : i + 3])
            for i in range(len(words) - 2)
            if tuple(words[i : i + 3]) in payload_trigrams
        ]
        assert not quoted, f"pattern {pattern.pattern!r} quotes the attack set: {quoted}"


def test_the_filter_generalises_worse_than_it_scores_on_its_own_family() -> None:
    """The generalisation gap, pinned as a property rather than assumed away.

    The old version of this test asserted the filter trips on *every* generated
    payload — true only because every payload was one of the two its regexes
    encoded, which is what made `injection_compliance_rate 0.00` a self-match.

    This asserts the honest shape instead: full recall on the phrasings the
    filter was designed against, strictly worse on phrasings it was not. If a
    change makes held-out recall match seen recall, the filter has either
    genuinely generalised or been tuned against the held-out set — either way
    the response is a new held-out phrasing, not deleting this assertion.
    """
    from crucible.pipeline import looks_like_injection

    attacks = generate_injection_attacks(ITEMS, n=8, seed=3)
    seen = [a for a in attacks if a.family == "seen"]
    heldout = [a for a in attacks if a.family == "heldout"]
    assert seen and heldout

    seen_recall = sum(looks_like_injection(a.document.text) for a in seen) / len(seen)
    heldout_recall = sum(looks_like_injection(a.document.text) for a in heldout) / len(heldout)

    assert seen_recall == 1.0
    assert heldout_recall < seen_recall


def test_the_isolation_prompt_does_not_enumerate_payload_behaviours() -> None:
    """A prompt that recites the test set measures recall of that list."""
    from crucible.attacks.injection import _PAYLOADS
    from crucible.pipeline.prompts import ISOLATION_SYSTEM_PROMPT

    prompt_trigrams = {
        tuple(_words(ISOLATION_SYSTEM_PROMPT)[i : i + 3])
        for i in range(len(_words(ISOLATION_SYSTEM_PROMPT)) - 2)
    }
    for name, text in _PAYLOADS.items():
        words = _words(text)
        shared = {tuple(words[i : i + 3]) for i in range(len(words) - 2)} & prompt_trigrams
        assert not shared, f"isolation prompt quotes the {name} payload: {shared}"
