"""Faithfulness suite: groundedness, hallucination rate, citation correctness.

Claim granularity is the sentence (deterministic splitter, v1) — the judge
decides entailment only, which keeps judge variance and cost down and makes
cached judgments maximally reusable. Definitions:

- groundedness        = supported claims / total claims, averaged over answers
                        that made at least one claim;
- hallucination_rate  = share of claim-making answers with ≥1 unsupported claim;
- answer_accuracy     = share of answers containing the gold answer string
                        (deterministic, judge-free);
- citation_parse_rate = share of answers whose [n] markers parsed (small local
                        generators often cite nothing — measured, not hidden);
- citation_precision  = of parsed citations, share whose chunk supports at
                        least one claim (omitted when nothing parsed).

Answers with no extractable claims (e.g. "I don't know.") are recorded but
excluded from groundedness/hallucination denominators — refusing to answer is
not hallucinating.
"""

from __future__ import annotations

import random
import re

from crucible.config import FaithfulnessSuiteConfig
from crucible.eval.concurrent import bounded_gather
from crucible.eval.judge import EntailmentJudge
from crucible.eval.metrics import mean
from crucible.eval.types import (
    CitationJudgment,
    ClaimJudgment,
    FaithfulnessRecord,
    Metric,
    SuiteResult,
)
from crucible.obs.aggregate import TimingCollector
from crucible.pipeline import Answer, RagPipeline
from crucible.qa import QAItem, answer_matches

SUITE = "faithfulness"

_MARKER_RE = re.compile(r"\[\d{1,3}\]")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]")
_MIN_CLAIM_CHARS = 20
_MAX_CLAIMS = 6
_MAX_CLAIMS_PER_CITATION = 3


def extract_claims(answer_text: str) -> list[str]:
    """Sentences of the answer, citation markers stripped, short fragments
    dropped. Deterministic by construction."""
    cleaned = _MARKER_RE.sub("", answer_text)
    claims = []
    for match in _SENTENCE_RE.findall(cleaned):
        claim = " ".join(match.split()).strip()
        if len(claim) >= _MIN_CLAIM_CHARS:
            claims.append(claim)
    return claims[:_MAX_CLAIMS]


async def run_faithfulness_suite(
    pipeline: RagPipeline,
    qa_items: list[QAItem],
    config: FaithfulnessSuiteConfig,
    judge: EntailmentJudge,
    seed: int,
    collector: TimingCollector,
    *,
    concurrency: int = 4,
) -> SuiteResult:
    sample = qa_items
    if config.sample_size is not None and config.sample_size < len(qa_items):
        sample = random.Random(seed).sample(qa_items, config.sample_size)
        sample.sort(key=lambda item: item.qid)

    async def evaluate_item(item: QAItem) -> FaithfulnessRecord:
        answer = await pipeline.answer(item.question)
        collector.add_all(_timings_dict(answer))
        return await _judge_answer(item, answer, judge)

    records = await bounded_gather([evaluate_item(item) for item in sample], concurrency)
    return SuiteResult(suite=SUITE, metrics=tuple(_aggregate(records)), records=tuple(records))


async def _judge_answer(item: QAItem, answer: Answer, judge: EntailmentJudge) -> FaithfulnessRecord:
    context_text = "\n\n".join(c.chunk.text for c in answer.context.candidates)
    claims = extract_claims(answer.text)
    judgments = []
    for claim in claims:
        verdict = await judge.supports(claim, context_text)
        judgments.append(
            ClaimJudgment(
                claim=claim,
                supported=verdict.supported,
                parse_ok=verdict.parse_ok,
                cached=verdict.cached,
            )
        )

    chunks_by_id = {c.chunk.chunk_id: c.chunk for c in answer.context.candidates}
    parsed_citations = [c for c in answer.citations if c.parsed]
    citation_judgments = []
    for citation in parsed_citations:
        chunk = chunks_by_id[citation.chunk_id]
        supports = False
        for claim in claims[:_MAX_CLAIMS_PER_CITATION]:
            if (await judge.supports(claim, chunk.text)).supported:
                supports = True
                break
        citation_judgments.append(
            CitationJudgment(chunk_id=citation.chunk_id, supports_claim=supports)
        )

    return FaithfulnessRecord(
        qid=item.qid,
        question=item.question,
        answer=answer.text,
        claims=tuple(judgments),
        citations_parsed=bool(parsed_citations),
        citations=tuple(citation_judgments),
        answer_match=answer_matches(answer.text, item),
    )


def _aggregate(records: list[FaithfulnessRecord]) -> list[Metric]:
    with_claims = [r for r in records if r.claims]
    groundedness = [sum(c.supported for c in r.claims) / len(r.claims) for r in with_claims]
    hallucinated = [any(not c.supported for c in r.claims) for r in with_claims]

    metrics = [
        Metric(suite=SUITE, name="groundedness", value=round(mean(groundedness), 4)),
        Metric(
            suite=SUITE,
            name="hallucination_rate",
            value=round(mean([float(h) for h in hallucinated]), 4),
        ),
        Metric(
            suite=SUITE,
            name="answer_accuracy",
            value=round(mean([float(r.answer_match) for r in records]), 4),
        ),
        Metric(
            suite=SUITE,
            name="citation_parse_rate",
            value=round(mean([float(r.citations_parsed) for r in records]), 4),
        ),
    ]
    all_citations = [c for r in records for c in r.citations]
    if all_citations:
        metrics.append(
            Metric(
                suite=SUITE,
                name="citation_precision",
                value=round(mean([float(c.supports_claim) for c in all_citations]), 4),
            )
        )
    return metrics


def _timings_dict(answer: Answer) -> dict[str, float]:
    timings = {
        "embed_query": answer.timings.embed_query_ms,
        "retrieve": answer.timings.retrieve_ms,
        "generate": answer.timings.generate_ms,
    }
    if answer.timings.rerank_ms is not None:
        timings["rerank"] = answer.timings.rerank_ms
    return timings
