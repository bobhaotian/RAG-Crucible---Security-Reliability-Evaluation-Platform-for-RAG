from __future__ import annotations

from crucible.pipeline import (
    Candidate,
    RankedContext,
    find_numeric_conflicts,
    resolve_numeric_conflicts,
)
from crucible.types import Chunk, Provenance, chunk_id_for


def _candidate(text: str, doc_id: str, source: str, provenance: Provenance) -> Candidate:
    return Candidate(
        chunk=Chunk(
            chunk_id=chunk_id_for(doc_id, 0, len(text)),
            doc_id=doc_id,
            source=source,
            text=text,
            start=0,
            end=len(text),
            provenance=provenance,
        ),
        score=1.0,
        rank=0,
    )


def test_detects_conflicting_values_for_the_same_query_and_unit() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0)
    upload = Provenance(source_type="user_upload", verified=False, trust_score=0.2)
    context = RankedContext(
        candidates=[
            _candidate(
                "The AT-300 has a battery life of 14 hours.",
                "official",
                "products/at-300-spec.md",
                trusted,
            ),
            _candidate(
                "In response to the AT-300 battery-life question, the value is 12 hours.",
                "upload",
                "uploads/updated-reference.md",
                upload,
            ),
        ],
        rerank_applied=True,
    )

    conflicts = find_numeric_conflicts("What is the AT-300 battery life?", context)

    assert len(conflicts) == 1
    assert conflicts[0].unit == "hours"
    assert conflicts[0].values == ("12", "14")
    assert {claim.trust_score for claim in conflicts[0].claims} == {0.2, 1.0}


def test_does_not_report_agreement_or_different_units_as_conflicts() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0)
    context = RankedContext(
        candidates=[
            _candidate("Battery life is 14 hours.", "manual", "manual.md", trusted),
            _candidate(
                "Battery life is 14 hours and charging takes 195 minutes.",
                "faq",
                "faq.md",
                trusted,
            ),
        ],
        rerank_applied=False,
    )

    assert find_numeric_conflicts("What is the battery life?", context) == []


def test_duplicate_chunks_from_one_document_do_not_create_a_conflict() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0)
    context = RankedContext(
        candidates=[
            _candidate("Old value 12 hours.", "manual", "manual.md", trusted),
            _candidate("New value 14 hours.", "manual", "manual.md", trusted),
        ],
        rerank_applied=False,
    )

    assert find_numeric_conflicts("What is the battery life?", context) == []


def test_resolver_keeps_unique_verified_winner_and_removes_loser() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0)
    upload = Provenance(source_type="user_upload", verified=False, trust_score=0.2)
    official = _candidate("Battery life is 14 hours.", "manual", "manual.md", trusted)
    unverified = _candidate("Battery life is 12 hours.", "upload", "upload.md", upload)
    context = RankedContext(candidates=[official, unverified], rerank_applied=True)

    decision = resolve_numeric_conflicts("What is the battery life?", context)

    assert decision.action == "proceed"
    assert decision.context.candidates == [official]
    assert decision.removed_chunks == 1
    assert decision.reason == "selected_unique_verified_winner"


def test_resolver_abstains_when_verified_sources_tie() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=1.0)
    context = RankedContext(
        candidates=[
            _candidate("Battery life is 14 hours.", "manual", "manual.md", trusted),
            _candidate("Battery life is 12 hours.", "faq", "faq.md", trusted),
        ],
        rerank_applied=False,
    )

    decision = resolve_numeric_conflicts("What is the battery life?", context)

    assert decision.action == "abstain"
    assert decision.context is context
    assert decision.reason == "conflicting_sources_without_a_unique_verified_winner"


def test_resolver_abstains_when_only_unverified_sources_disagree() -> None:
    upload = Provenance(source_type="user_upload", verified=False, trust_score=0.2)
    context = RankedContext(
        candidates=[
            _candidate("Battery life is 14 hours.", "upload-a", "a.md", upload),
            _candidate("Battery life is 12 hours.", "upload-b", "b.md", upload),
        ],
        rerank_applied=False,
    )

    decision = resolve_numeric_conflicts("What is the battery life?", context)

    assert decision.action == "abstain"


def test_resolver_counts_independent_documents_not_duplicate_chunks() -> None:
    trusted = Provenance(source_type="trusted_corpus", verified=True, trust_score=0.6)
    upload = Provenance(source_type="user_upload", verified=False, trust_score=0.2)
    context = RankedContext(
        candidates=[
            _candidate("Battery life is 14 hours.", "manual-a", "a.md", trusted),
            _candidate("Battery life is 14 hours.", "manual-b", "b.md", trusted),
            _candidate("Battery life is 12 hours.", "upload", "upload.md", upload),
        ],
        rerank_applied=False,
    )

    decision = resolve_numeric_conflicts("What is the battery life?", context)

    assert decision.action == "proceed"
    assert [candidate.chunk.doc_id for candidate in decision.context.candidates] == [
        "manual-a",
        "manual-b",
    ]
