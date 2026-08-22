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
            qid="q1", question="one", answer="answer",
            claims=(
                ClaimJudgment(claim="supported", supported=True, parse_ok=True, cached=False),
                ClaimJudgment(claim="unsupported", supported=False, parse_ok=True, cached=False),
            ),
            citations_parsed=True,
            citations=(CitationJudgment(chunk_id="c1", supports_claim=True),),
            answer_match=True,
        ),
        FaithfulnessRecord(
            qid="q2", question="two", answer="refusal", claims=(),
            citations_parsed=False, citations=(), answer_match=False,
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
        qid="q1", question="one", answer="answer", claims=(),
        citations_parsed=False, citations=(), answer_match=False,
    )

    assert "citation_precision" not in {metric.name for metric in _aggregate([record])}
