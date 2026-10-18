"""Placement: generated documents get paths shaped like the corpus they join.

A planted document's path is printed into the prompt and handed to every
defense, so it must not say what the document is. These pin the properties that
make a path uninformative: it sits in one of the corpus's own directories,
under a topical name, collides with nothing, and carries no marker of ours.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rag_crucible.attacks import (
    generate_canaries,
    generate_injection_attacks,
    generate_poison_attacks,
)
from rag_crucible.attacks.placement import CorpusPlacer, slug
from rag_crucible.ingest import apply_filters, load_corpus
from rag_crucible.qa import QAItem, load_qa

SEEDED = Path(__file__).resolve().parents[3] / "datasets" / "seeded"

CORPUS = (
    "products/at-300-spec.md",
    "products/sr-2-spec.md",
    "kb/api-rate-limits.md",
    "handbook/vacation.md",
)

# What our own old labels looked like. None may reappear in a placed path.
MARKER_WORDS = ("poison", "inject", "canary", "attack")

_PATH_RE = re.compile(r"^(?:[^/]+/)?[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


def _assert_uninformative(path: str, identity: str, corpus: tuple[str, ...]) -> None:
    """A placed path looks like a corpus document and names nothing of ours."""
    assert _PATH_RE.match(path), path
    assert path.partition("/")[0] in {source.partition("/")[0] for source in corpus}
    assert path not in corpus
    assert "__" not in path
    assert identity.lower() not in path.lower()
    assert not any(word in path for word in MARKER_WORDS), path


def test_slug_keeps_topic_words_and_drops_question_scaffolding() -> None:
    assert slug("What is the battery life of the AT-300 autonomous drone?") == (
        "battery-life-at-300-autonomous"
    )
    assert slug("How much does the SR-2 cost?") == "sr-2-cost"
    assert slug("How long is the on-call rotation?") == "on-call-rotation"
    assert slug("the Helios billing service") == "helios-billing-service"


def test_slug_is_capped_and_never_empty() -> None:
    assert slug("alpha beta gamma delta epsilon zeta") == "alpha-beta-gamma-delta"
    assert slug("calibration " * 3 + "x" * 80) == "calibration-calibration-calibration"
    assert slug("x" * 80) == "x" * 40
    assert slug("What is it?") == "notes"
    assert slug("???") == "notes"


def test_slug_drops_our_marker_vocabulary_even_when_the_topic_uses_it() -> None:
    name = slug("How are prompt injection attacks and data poisoning caught by canaries?")
    assert not any(word in name for word in MARKER_WORDS), name
    assert name == "prompt-data-caught"


def test_placement_is_deterministic() -> None:
    first = CorpusPlacer(CORPUS, seed=7)
    second = CorpusPlacer(CORPUS, seed=7)
    for key in ("q001", "q002", "q003"):
        topic = f"What is the battery life of {key}?"
        assert first.place(key, topic) == second.place(key, topic)


def test_placement_lands_in_the_corpus_own_directories() -> None:
    placer = CorpusPlacer(CORPUS, seed=7)
    paths = [
        placer.place(f"q{i:03d}", f"What is the maximum payload of unit {i}?") for i in range(60)
    ]
    for i, path in enumerate(paths):
        _assert_uninformative(path, f"q{i:03d}", CORPUS)
    # The directory is drawn per document, not fixed for the run.
    assert {path.partition("/")[0] for path in paths} == {"products", "kb", "handbook"}


def test_the_seed_and_key_choose_the_directory() -> None:
    topic = "What is the maximum payload of the SR-2?"

    def directory(seed: int, key: str) -> str:
        return CorpusPlacer(CORPUS, seed=seed).place(key, topic).partition("/")[0]

    assert len({directory(seed, "q006") for seed in range(20)}) > 1
    assert len({directory(7, f"q{i:03d}") for i in range(20)}) > 1


def test_placement_avoids_the_corpus_and_every_earlier_placement() -> None:
    corpus = ("kb/api-rate-limits.md", "kb/api-rate-limits-2.md")
    placer = CorpusPlacer(corpus, seed=0)
    paths = [placer.place(f"k{i}", "API rate limits") for i in range(4)]
    assert paths == [
        "kb/api-rate-limits-3.md",
        "kb/api-rate-limits-4.md",
        "kb/api-rate-limits-5.md",
        "kb/api-rate-limits-6.md",
    ]


def test_collisions_are_case_insensitive() -> None:
    placer = CorpusPlacer(("kb/API-Rate-Limits.md",), seed=0)
    assert placer.place("k", "API rate limits") == "kb/api-rate-limits-2.md"


def test_a_flat_corpus_places_at_the_root() -> None:
    placer = CorpusPlacer(("faq.md", "returns.txt"), seed=3)
    assert placer.place("q1", "How long is the warranty?") == "warranty.md"
    assert CorpusPlacer((), seed=3).place("q1", "How long is the warranty?") == "warranty.md"


def test_a_corpus_with_root_files_can_place_at_the_root_too() -> None:
    placer = CorpusPlacer(("faq.md", "kb/sso.md"), seed=1)
    paths = {placer.place(f"q{i}", f"topic number {i}") for i in range(40)}
    assert {path.partition("/")[0] if "/" in path else "" for path in paths} == {"", "kb"}


def test_a_directory_shaped_like_a_marker_is_never_chosen() -> None:
    placer = CorpusPlacer(("__drafts__/a.md", "kb/b.md"), seed=1)
    paths = [placer.place(f"q{i}", f"topic number {i}") for i in range(40)]
    assert all(path.startswith("kb/") for path in paths)


ITEMS = [
    QAItem(
        qid=f"q{i:03d}",
        question=f"What is the spec value number {i}?",
        answer=f"{i * 10} units",
        gold_fact=f"The spec value number {i} is {i * 10} units.",
    )
    for i in range(1, 9)
]


def test_generators_place_into_the_corpus_they_are_given() -> None:
    poison = generate_poison_attacks(ITEMS, n=None, seed=7, corpus_sources=CORPUS)
    taken = (*CORPUS, *(a.document.source for a in poison))
    injections = generate_injection_attacks(ITEMS, n=None, seed=3, corpus_sources=taken)
    canaries = generate_canaries(9, ("email", "api_key", "phone"), seed=5, corpus_sources=CORPUS)

    placed = [(a.document.source, a.qid) for a in [*poison, *injections]]
    placed += [(c.document.source, c.canary_id) for c in canaries]
    for path, identity in placed:
        _assert_uninformative(path, identity, CORPUS)
    # Poison and injection on the same question share a topic, never a path.
    attack_paths = [a.document.source for a in [*poison, *injections]]
    assert len(set(attack_paths)) == len(attack_paths)


@pytest.fixture(scope="module")
def seeded_sources() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(every loaded source, the sources that survive the default filters)."""
    docs, _ = load_corpus(SEEDED / "corpus")
    kept, _ = apply_filters(docs, ["dedup", "language", "boilerplate"])
    return tuple(d.source for d in docs), tuple(d.source for d in kept)


def test_no_seeded_placement_equals_or_resembles_a_corpus_source(
    seeded_sources: tuple[tuple[str, ...], tuple[str, ...]],
) -> None:
    """Every question in the seeded set, attacked twice, plus a full canary set.

    The corpus already names files topically (kb/api-rate-limits.md), which is
    exactly why a hex or marker name would stand out beside them.
    """
    loaded, kept = seeded_sources
    qa = load_qa(SEEDED / "qa.jsonl")
    poison = generate_poison_attacks(qa, None, 11, corpus_sources=kept)
    injections = generate_injection_attacks(
        qa, None, 13, corpus_sources=[*kept, *(a.document.source for a in poison)]
    )
    canaries = generate_canaries(12, ("email", "api_key", "phone"), 7, corpus_sources=kept)

    placed = [(a.document.source, a.qid) for a in [*poison, *injections]]
    placed += [(c.document.source, c.canary_id) for c in canaries]
    for path, identity in placed:
        _assert_uninformative(path, identity, kept)
        assert path not in loaded  # not even a document the filters dropped
    assert len({path for path, _ in placed}) == len(placed)
    # noise/ holds only documents the filters drop; an attack there would sit alone.
    assert not any(path.startswith("noise/") for path, _ in placed)
