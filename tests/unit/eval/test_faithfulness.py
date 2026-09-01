from __future__ import annotations

from crucible.eval.faithfulness import _aggregate, extract_claims
from crucible.eval.types import CitationJudgment, ClaimJudgment, FaithfulnessRecord


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


def test_aggregate_omits_precision_without_citations() -> None:
    record = FaithfulnessRecord(
        qid="q1",
        question="one",
        answer="answer",
        claims=(),
        citations_parsed=False,
        citations=(),
        answer_match=False,
    )

    assert "citation_precision" not in {metric.name for metric in _aggregate([record])}


def test_aggregate_omits_answer_accuracy_when_no_item_carries_a_gold_answer() -> None:
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
    names = {metric.name for metric in _aggregate(records)}

    assert "answer_accuracy" not in names
    assert "groundedness" in names  # the rest of the suite still reports


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
