"""Defenses decide on content and provenance, never on the source path.

The source is the one chunk field the evaluator used to control: it labelled
planted documents ``__inject__/q007.md``. A defense that read it would score a
perfect screen without recognising a single attack, and no metric would show
it. Planted on 17 Oct, ``startswith("__inject__")`` inside
``filter_injected_chunks`` left every test passing and lifted held-out
screening from 0.33 to 1.00.

So every defense entry point runs over the same contexts under four
labellings of the sources: the corpus-shaped paths placement gives, the old
evaluator labels, an unrelated corpus-like path per document, and numbered
siblings (``kb/notes.md``, ``kb/notes-2.md``), the shape a name collision
used to give a twin. Ids, text and
provenance are untouched, so a decision that moves can only have read the path.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import get_args

import pytest

from rag_crucible.attacks import (
    PoisonAttack,
    generate_canaries,
    generate_injection_attacks,
    generate_poison_attacks,
)
from rag_crucible.config import ChunkerConfig, DefenseName
from rag_crucible.ingest import apply_filters, chunk_documents, load_corpus
from rag_crucible.pipeline import (
    Candidate,
    RankedContext,
    filter_injected_chunks,
    filter_untrusted_chunks,
    resolve_numeric_conflicts,
)
from rag_crucible.pipeline.defenses import clean_chunk_screening_reason
from rag_crucible.qa import load_qa
from rag_crucible.types import Chunk, Document

SEEDED = Path(__file__).resolve().parents[3] / "datasets" / "seeded"
CHUNKER = ChunkerConfig()
DEFENSES: tuple[str, ...] = get_args(DefenseName)

Labeller = dict[str, str]  # doc_id -> the source to show for it


@dataclass(frozen=True)
class Case:
    name: str
    query: str
    context: RankedContext
    evaluator_labels: Labeller  # what the planted documents used to be called


def _planted_chunks(documents: list[Document]) -> list[Chunk]:
    """Alternate the ingestion channel, so the provenance defenses have
    something real to decide on; the suites themselves use the corpus channel."""
    chunks: list[Chunk] = []
    for i, document in enumerate(documents):
        channel = "user_upload" if i % 2 else "trusted_corpus"
        chunks += chunk_documents([document], CHUNKER, source_channel=channel)
    return chunks


def _context(chunks: list[Chunk]) -> RankedContext:
    return RankedContext(
        candidates=[
            Candidate(chunk=chunk, score=1.0 - rank / 100, rank=rank)
            for rank, chunk in enumerate(chunks)
        ],
        rerank_applied=True,
    )


def _cases() -> list[Case]:
    qa = load_qa(SEEDED / "qa.jsonl")
    docs, _ = load_corpus(SEEDED / "corpus")
    kept, _ = apply_filters(docs, ["dedup", "language", "boilerplate"])
    sources = [doc.source for doc in kept]
    poison = generate_poison_attacks(qa, 8, 11, corpus_sources=sources)
    injections = generate_injection_attacks(
        qa, 8, 13, corpus_sources=[*sources, *(a.document.source for a in poison)]
    )
    canaries = generate_canaries(6, ("email", "api_key", "phone"), 7, corpus_sources=sources)

    labels: Labeller = {a.document.doc_id: f"__poison__/{a.qid}.md" for a in poison}
    labels |= {a.document.doc_id: f"__inject__/{a.qid}.md" for a in injections}
    labels |= {c.document.doc_id: f"__canary__/{c.canary_id}.md" for c in canaries}

    planted_docs = [a.document for a in [*poison, *injections]] + [c.document for c in canaries]
    planted = _planted_chunks(planted_docs)
    clean = chunk_documents(kept, CHUNKER)
    gold = {item.qid: item.gold_doc for item in qa}

    def neighbours(doc_id: str) -> list[Chunk]:
        """Two other planted documents, so a context holds rival attacks too."""
        order = [d.doc_id for d in planted_docs]
        start = order.index(doc_id)
        rivals = {order[(start + step) % len(order)] for step in (1, 5)}
        return [chunk for chunk in planted if chunk.doc_id in rivals]

    cases: list[Case] = []
    for attack in [*poison, *injections]:
        own = [chunk for chunk in planted if chunk.doc_id == attack.document.doc_id]
        # The genuine source of the fact, so poison meets the value it contradicts.
        truth = [chunk for chunk in clean if chunk.source == gold[attack.qid]]
        kind = "poison" if isinstance(attack, PoisonAttack) else "injection"
        cases.append(
            Case(
                name=f"{kind}-{attack.qid}",
                query=attack.question,
                context=_context(own + truth + neighbours(attack.document.doc_id)),
                evaluator_labels=labels,
            )
        )
        if kind == "poison":  # alone with the truth, an untrusted poison is outvoted
            cases.append(
                Case(
                    name=f"poison-{attack.qid}-alone",
                    query=attack.question,
                    context=_context(own + truth),
                    evaluator_labels=labels,
                )
            )
    for canary in canaries:
        own = [chunk for chunk in planted if chunk.doc_id == canary.document.doc_id]
        cases.append(
            Case(
                name=f"canary-{canary.canary_id}",
                query=canary.probes["direct"],
                context=_context(own + clean[:2] + neighbours(canary.document.doc_id)),
                evaluator_labels=labels,
            )
        )
    return cases


CASES = _cases()


def _relabel(context: RankedContext, sources: Labeller) -> RankedContext:
    """The same context with only ``Chunk.source`` replaced (by doc_id)."""
    return RankedContext(
        candidates=[
            candidate.model_copy(
                update={
                    "chunk": candidate.chunk.model_copy(
                        update={
                            "source": sources.get(candidate.chunk.doc_id, candidate.chunk.source)
                        }
                    )
                }
            )
            for candidate in context.candidates
        ],
        rerank_applied=context.rerank_applied,
    )


def _unrelated(context: RankedContext) -> Labeller:
    """A corpus-like path per document that says nothing about any of them."""
    names: Labeller = {}
    for candidate in context.candidates:
        names.setdefault(candidate.chunk.doc_id, f"archive/doc-{len(names):03d}.md")
    return names


def _siblings(context: RankedContext) -> Labeller:
    """Every document named as a numbered copy of the first, so a defense that
    reads ``x-2.md`` beside ``x.md`` as "the copy" decides differently here."""
    names: Labeller = {}
    for candidate in context.candidates:
        n = len(names)
        names.setdefault(
            candidate.chunk.doc_id, "kb/notes.md" if n == 0 else f"kb/notes-{n + 1}.md"
        )
    return names


def _kept(context: RankedContext) -> tuple[str, ...]:
    return tuple(candidate.chunk.chunk_id for candidate in context.candidates)


@dataclass(frozen=True)
class Decisions:
    """Everything each defense decides about one context, minus the paths it
    echoes back (a numeric claim carries its chunk's source as provenance)."""

    filter_injected_chunks: tuple[tuple[str, ...], int]
    filter_untrusted_chunks: tuple[tuple[str, ...], int]
    resolve_numeric_conflicts: tuple[object, ...]
    clean_chunk_screening_reason: tuple[str | None, ...]


def _decide(query: str, context: RankedContext) -> Decisions:
    screened, screened_out = filter_injected_chunks(context)
    trusted, untrusted_out = filter_untrusted_chunks(context)
    resolved = resolve_numeric_conflicts(query, context)
    return Decisions(
        filter_injected_chunks=(_kept(screened), screened_out),
        filter_untrusted_chunks=(_kept(trusted), untrusted_out),
        resolve_numeric_conflicts=(
            resolved.action,
            resolved.reason,
            resolved.removed_chunks,
            _kept(resolved.context),
            tuple(
                (conflict.unit, conflict.values, tuple(c.chunk_id for c in conflict.claims))
                for conflict in resolved.conflicts
            ),
        ),
        clean_chunk_screening_reason=tuple(
            clean_chunk_screening_reason(candidate.chunk, defense)
            for candidate in context.candidates
            for defense in DEFENSES
        ),
    )


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_defense_decisions_do_not_depend_on_the_source(case: Case) -> None:
    placed = _decide(case.query, case.context)
    labelled = _decide(case.query, _relabel(case.context, case.evaluator_labels))
    unrelated = _decide(case.query, _relabel(case.context, _unrelated(case.context)))
    siblings = _decide(case.query, _relabel(case.context, _siblings(case.context)))
    for defense in (f.name for f in fields(Decisions)):
        expected = getattr(unrelated, defense)
        assert getattr(placed, defense) == expected, f"{defense} read the placed path"
        assert getattr(labelled, defense) == expected, f"{defense} read the evaluator label"
        assert getattr(siblings, defense) == expected, f"{defense} read a numbered name"


def test_the_cases_exercise_every_kind_of_decision() -> None:
    """A defense that never acts is trivially source-blind. Each one must act
    somewhere, or the test above has nothing to compare."""
    decided = [_decide(case.query, case.context) for case in CASES]
    assert any(d.filter_injected_chunks[1] for d in decided)
    assert any(d.filter_untrusted_chunks[1] for d in decided)
    assert {d.resolve_numeric_conflicts[0] for d in decided} == {"proceed", "abstain"}
    assert any(d.resolve_numeric_conflicts[2] for d in decided)  # a rival value removed
    assert any(reason for d in decided for reason in d.clean_chunk_screening_reason)
    # Every planted document is shown under its old label somewhere.
    shown = {c.chunk.doc_id for case in CASES for c in case.context.candidates}
    assert set(CASES[0].evaluator_labels) <= shown
