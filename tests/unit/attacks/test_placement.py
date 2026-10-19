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
from rag_crucible.attacks.placement import CorpusPlacer, _candidate_names, slug
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


def test_slug_is_capped() -> None:
    assert slug("alpha beta gamma delta epsilon zeta") == "alpha-beta-gamma-delta"
    assert slug("calibration " * 3 + "x" * 80) == "calibration-calibration-calibration"
    assert slug("x" * 80) == "x" * 40
    assert slug("What is it?") == ""  # no content words; placement falls back


def test_slug_folds_accents_instead_of_splitting_on_them() -> None:
    assert slug("¿Cuál es la política de reembolso?") == "cual-es-la-politica"
    assert slug("Wie lange dauert die Rückerstattung?") == "wie-lange-dauert-die"


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


_NUMBERED = re.compile(r"^(.+)-\d+\.md$")


def _numbered_siblings(paths: list[str], corpus: tuple[str, ...] = ()) -> list[str]:
    """Paths named ``x-N.md`` beside an ``x.md`` among the others or the corpus,
    in any directory: the shape that marks one document as the other's copy.
    A topic that ends in a number of its own ("unit 2") is not one."""
    names = [path.rpartition("/")[2] for path in [*paths, *corpus]]
    found = []
    for path in paths:
        match = _NUMBERED.match(path.rpartition("/")[2])
        if match and f"{match.group(1)}.md" in names:
            found.append(path)
    return found


def test_a_collision_takes_another_topical_name_not_a_numbered_sibling() -> None:
    """``x-2.md`` beside ``x.md`` marks the second as the copy, so while any
    topical or neutral name is free, no name is numbered."""
    corpus = ("kb/api-rate-limits.md",)
    placer = CorpusPlacer(corpus, seed=0)
    paths = [placer.place(f"k{i}", "API rate limits") for i in range(4)]
    assert len(set(paths)) == 4
    assert not set(paths) & set(corpus)
    assert not _numbered_siblings(paths, corpus), paths
    assert {"kb/api-rate.md", "kb/rate-limits.md"} <= set(paths)


def test_only_an_exhausted_name_space_is_numbered() -> None:
    names = list(_candidate_names(0, "k", "API rate limits", ()))
    assert len(names) > 20  # windows, qualified windows, neutral names
    corpus = tuple(f"kb/{name}.md" for name in names)
    assert _numbered_siblings([CorpusPlacer(corpus, seed=0).place("k", "API rate limits")], corpus)


def test_collisions_are_case_insensitive() -> None:
    placer = CorpusPlacer(("kb/API-Rate-Limits.md",), seed=0)
    assert placer.place("k", "API rate limits").lower() != "kb/api-rate-limits.md"


def test_a_dropped_corpus_file_is_never_reused() -> None:
    """``avoid`` holds sources that set no directory, such as a file the ingest
    filters dropped: the run's audit names it, so a planted twin would clash."""
    placer = CorpusPlacer(("kb/guide.md",), seed=0, avoid=("kb/warranty.md",))
    for i in range(5):
        assert placer.place(f"k{i}", "How long is the warranty?") != "kb/warranty.md"


def test_no_two_planted_documents_share_a_file_name() -> None:
    """Twins on one question in different directories would show the same file
    name twice in one prompt."""
    placer = CorpusPlacer(CORPUS, seed=2)
    paths = [placer.place(f"{kind}:q001", "What is the SR-2 payload?") for kind in ("p", "i", "c")]
    names = [path.rpartition("/")[2] for path in paths]
    assert len(set(names)) == len(names), paths


def test_topics_with_no_latin_words_get_neutral_names_not_a_count() -> None:
    placer = CorpusPlacer(("kb/a.md",), seed=4)
    paths = [placer.place(f"k{i}", "退款政策是什么") for i in range(6)]
    assert len(set(paths)) == 6
    assert not _numbered_siblings(paths), paths


def test_hidden_words_never_reach_the_path() -> None:
    placer = CorpusPlacer(CORPUS, seed=1)
    assert "q001" not in placer.place("poison:q001", "What is q001 battery life?", hide=("q001",))


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
    injections = generate_injection_attacks(
        ITEMS, n=None, seed=3, corpus_sources=CORPUS, avoid=[a.document.source for a in poison]
    )
    canaries = generate_canaries(9, ("email", "api_key", "phone"), seed=5, corpus_sources=CORPUS)

    placed = [(a.document.source, a.qid) for a in [*poison, *injections]]
    placed += [(c.document.source, c.canary_id) for c in canaries]
    for path, identity in placed:
        _assert_uninformative(path, identity, CORPUS)
    # Poison and injection on the same question share a topic, never a path or
    # a file name, and neither is a numbered copy of the other.
    attack_paths = [a.document.source for a in [*poison, *injections]]
    assert len({path.rpartition("/")[2] for path in attack_paths}) == len(attack_paths)
    assert not _numbered_siblings(attack_paths, CORPUS), attack_paths


def test_twins_on_a_single_directory_corpus_are_not_numbered_copies() -> None:
    """The shape a flat or one-folder user corpus has, with poison and
    injection both targeting every question (disjoint_targets is off by
    default). This is where a numbered sibling used to appear."""
    corpus = ("kb/intro.md", "kb/setup.md")
    poison = generate_poison_attacks(ITEMS, n=None, seed=7, corpus_sources=corpus)
    injections = generate_injection_attacks(
        ITEMS, n=None, seed=3, corpus_sources=corpus, avoid=[a.document.source for a in poison]
    )
    paths = [a.document.source for a in [*poison, *injections]]
    assert not _numbered_siblings(paths, corpus), paths
    assert len({path.rpartition("/")[2] for path in paths}) == len(paths)


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
    poison = generate_poison_attacks(qa, None, 11, corpus_sources=kept, avoid=loaded)
    injections = generate_injection_attacks(
        qa, None, 13, corpus_sources=kept, avoid=[*loaded, *(a.document.source for a in poison)]
    )
    canaries = generate_canaries(
        12, ("email", "api_key", "phone"), 7, corpus_sources=kept, avoid=loaded
    )

    placed = [(a.document.source, a.qid) for a in [*poison, *injections]]
    placed += [(c.document.source, c.canary_id) for c in canaries]
    for path, identity in placed:
        _assert_uninformative(path, identity, kept)
        assert path not in loaded  # not even a document the filters dropped
    assert len({path for path, _ in placed}) == len(placed)
    assert not _numbered_siblings([path for path, _ in placed], loaded)
    # noise/ holds only documents the filters drop; an attack there would sit alone.
    assert not any(path.startswith("noise/") for path, _ in placed)
