from __future__ import annotations

from rag_crucible.eval.faithfulness import _aggregate, extract_claims
from rag_crucible.eval.types import CitationJudgment, ClaimJudgment, FaithfulnessRecord


def test_extract_claims_strips_markers_drops_fragments_and_caps_results() -> None:
    sentences = [f"This is sufficiently long factual sentence number {i} [1]." for i in range(8)]
    claims = extract_claims("Short. " + " ".join(sentences))

    assert len(claims) == 6
    assert all("[1]" not in claim for claim in claims)
    assert claims[0].endswith("number 0 .")


def test_aggregate_uses_the_intended_denominators() -> None:
    records = [
        FaithfulnessRecord(
            qid="q1",
            question="one",
            answer="answer",
            claims=(
                ClaimJudgment(claim="supported", supported=True, parse_ok=True, cached=False),
                ClaimJudgment(claim="unsupported", supported=False, parse_ok=True, cached=False),
            ),
            citations_parsed=True,
            citations=(CitationJudgment(chunk_id="c1", supports_claim=True),),
            answer_match=True,
        ),
        FaithfulnessRecord(
            qid="q2",
            question="two",
            answer="refusal",
            claims=(),
            citations_parsed=False,
            citations=(),
            answer_match=False,
        ),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records)}

    assert metrics[("groundedness", "")] == 0.5
    assert metrics[("hallucination_rate", "")] == 1.0
    assert metrics[("answer_accuracy", "")] == 0.5
    assert metrics[("citation_parse_rate", "")] == 0.5
    assert metrics[("citation_precision", "")] == 1.0


def test_precision_without_citations_is_not_estimable_rather_than_omitted() -> None:
    record = FaithfulnessRecord(
        qid="q1",
        question="one",
        answer="answer",
        claims=(),
        citations_parsed=False,
        citations=(),
        answer_match=False,
    )

    precision = next(m for m in _aggregate([record]) if m.name == "citation_precision")
    assert precision.value is None and precision.state == "not_estimable"
    assert precision.n == 0


def test_answer_accuracy_is_unsupported_when_no_item_carries_a_gold_answer() -> None:
    """A doc-id-labeled corpus (BEIR `gold_docs`) has no answer strings.

    Scoring those items as misses would publish `answer_accuracy 0.0000` as if it
    were measured, on the one metric the README calls deterministic.
    """
    records = [
        FaithfulnessRecord(
            qid=qid,
            question="q",
            answer="answer",
            claims=(ClaimJudgment(claim="c", supported=True, parse_ok=True, cached=False),),
            citations_parsed=False,
            citations=(),
            answer_match=None,
        )
        for qid in ("q1", "q2")
    ]
    metrics = {metric.name: metric for metric in _aggregate(records)}

    accuracy = metrics["answer_accuracy"]
    assert accuracy.value is None and accuracy.state == "unsupported"
    assert (accuracy.n, accuracy.n_excluded) == (0, 2)
    assert metrics["groundedness"].value == 1.0  # the rest of the suite still reports


def test_aggregate_scores_answer_accuracy_over_gradable_items_only() -> None:
    records = [
        FaithfulnessRecord(
            qid="q1",
            question="q",
            answer="answer",
            claims=(),
            citations_parsed=False,
            citations=(),
            answer_match=True,
        ),
        FaithfulnessRecord(
            qid="q2",
            question="q",
            answer="answer",
            claims=(),
            citations_parsed=False,
            citations=(),
            answer_match=None,  # unlabelled: must not dilute the rate
        ),
    ]
    metrics = {m.name: m.value for m in _aggregate(records)}

    assert metrics["answer_accuracy"] == 1.0


def test_a_citation_with_no_claim_to_check_is_not_judged_unsupported() -> None:
    """An answer with no claim gives its citations nothing to support, so they
    are unjudged and left out of citation_precision, not counted as misses."""
    from rag_crucible.eval.types import CitationJudgment

    judged = FaithfulnessRecord(
        qid="q1",
        question="one",
        answer="The X1 lasts 72 hours [1].",
        claims=(ClaimJudgment(claim="c", supported=True, parse_ok=True, cached=False),),
        citations_parsed=True,
        citations=(CitationJudgment(chunk_id="a", supports_claim=True),),
        answer_match=None,
    )
    unjudged = judged.model_copy(
        update={
            "qid": "q2",
            "claims": (),
            "citations": (CitationJudgment(chunk_id="b", supports_claim=None),),
        }
    )
    precision = next(m for m in _aggregate([judged, unjudged]) if m.name == "citation_precision")
    assert precision.value == 1.0
    assert (precision.n, precision.n_excluded) == (1, 1)


async def test_the_judge_leaves_a_citation_unjudged_when_its_answer_made_no_claim() -> None:
    """The producer side: an answer too terse to yield a claim still cites a
    chunk, and that citation is recorded as not judged rather than unsupported."""
    from rag_crucible.eval.faithfulness import _judge_answer
    from rag_crucible.eval.judge import HeuristicJudge
    from rag_crucible.pipeline.types import (
        Answer,
        Candidate,
        Citation,
        RankedContext,
        StageTimings,
    )
    from rag_crucible.providers.base import Usage
    from rag_crucible.qa import QAItem
    from rag_crucible.types import Chunk

    chunk = Chunk(
        chunk_id="c1",
        doc_id="d1",
        source="kb/x1.md",
        text="The X1 lasts 72 hours.",
        start=0,
        end=22,
    )
    answer = Answer(
        text="72 hours [1]",  # no sentence ending in . ! or ?, so no claim
        citations=[Citation(chunk_id="c1", marker=1, parsed=True)],
        context=RankedContext(
            candidates=[Candidate(chunk=chunk, score=1.0, rank=0)], rerank_applied=False
        ),
        usage=Usage(),
        timings=StageTimings(
            embed_query_ms=0, retrieve_ms=0, rerank_ms=None, generate_ms=0, total_ms=0
        ),
    )
    record = await _judge_answer(QAItem(qid="q1", question="How long?"), answer, HeuristicJudge())

    assert record.claims == ()
    assert [c.supports_claim for c in record.citations] == [None]


def test_claim_metrics_count_the_answers_that_made_no_claim() -> None:
    with_claim = FaithfulnessRecord(
        qid="q1",
        question="one",
        answer="a",
        citations_parsed=False,
        citations=(),
        claims=(ClaimJudgment(claim="c", supported=False, parse_ok=True, cached=False),),
        answer_match=None,
    )
    terse = with_claim.model_copy(update={"qid": "q2", "claims": ()})
    metrics = {m.name: m for m in _aggregate([with_claim, terse])}
    for name in ("groundedness", "hallucination_rate"):
        assert (metrics[name].n, metrics[name].n_excluded) == (1, 1), name
    assert (metrics["citation_parse_rate"].n, metrics["citation_parse_rate"].n_excluded) == (2, 0)
