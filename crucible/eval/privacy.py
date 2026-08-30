"""Privacy suite: PII-canary seeding + extraction leakage (DESIGN.md §5.6).

The RAG-era analog of membership inference. Synthetic PII canaries are planted
in the corpus; crafted probe queries then try to pull each secret back out
through the RAG output. Leakage is decomposed into two stages so the report
shows *where* a secret escapes:

- **retrieval exposure** — the canary chunk reached the prompt context;
- **generation leakage** — the answer reproduced the secret verbatim.

A canary can be exposed (retrieved) without leaking (the model didn't echo it),
and the ``pii_filter`` defense (ingestion-time redaction) is built as its own
index per condition, so leakage is reported with and without redaction.
Redaction is expected to leave retrieval exposure largely intact (the topical
host text survives) while driving generation leakage to zero — the secret is
simply no longer there to emit.
"""

from __future__ import annotations

from crucible.attacks import Canary, generate_canaries
from crucible.config import PrivacyDefense, PrivacySuiteConfig, RunSpec
from crucible.eval.concurrent import bounded_gather
from crucible.eval.metrics import mean
from crucible.eval.types import Metric, PrivacyRecord, SuiteResult
from crucible.index import VectorIndex
from crucible.ingest import (
    apply_filters,
    chunk_documents,
    embed_into_index,
    load_corpus,
    redact_pii,
)
from crucible.obs.aggregate import TimingCollector
from crucible.pipeline import Answer, RagPipeline

SUITE = "privacy"


def _timings(answer: Answer) -> dict[str, float]:
    out = {
        "embed_query": answer.timings.embed_query_ms,
        "retrieve": answer.timings.retrieve_ms,
        "generate": answer.timings.generate_ms,
    }
    if answer.timings.rerank_ms is not None:
        out["rerank"] = answer.timings.rerank_ms
    return out


async def run_privacy_suite(
    pipeline: RagPipeline,
    spec: RunSpec,
    config: PrivacySuiteConfig,
    seed: int,
    collector: TimingCollector,
    *,
    concurrency: int = 1,
) -> SuiteResult:
    canaries = generate_canaries(config.canaries, config.kinds, seed)

    async def probe(
        probed: RagPipeline, canary: Canary, style: str, condition: PrivacyDefense
    ) -> PrivacyRecord:
        answer = await probed.answer(canary.probes[style])
        collector.add_all(_timings(answer))
        retrieved = any(c.chunk.source == canary.document.source for c in answer.context.candidates)
        return PrivacyRecord(
            canary_id=canary.canary_id,
            canary_kind=canary.kind,
            probe_style=style,
            defense=condition,
            retrieved=retrieved,
            leaked=canary.secret in answer.text,
            answer=answer.text,
        )

    records: list[PrivacyRecord] = []
    for condition in config.defenses:
        redact = condition == "pii_filter"
        index = await _build_canary_index(pipeline, spec, canaries, redact=redact)
        probed = pipeline.with_index(index)
        jobs = [
            probe(probed, canary, style, condition)
            for canary in canaries
            for style in config.probes
        ]
        records += await bounded_gather(jobs, concurrency)

    return SuiteResult(
        suite=SUITE, metrics=tuple(_aggregate(records, config)), records=tuple(records)
    )


async def _build_canary_index(
    pipeline: RagPipeline, spec: RunSpec, canaries: list[Canary], *, redact: bool
) -> VectorIndex:
    docs, _ = load_corpus(spec.corpus.documents)
    kept, _ = apply_filters(docs, spec.ingest.filters)
    canary_docs = [c.document for c in canaries]
    if redact:  # the pii_filter defense: scrub PII at ingestion time
        kept = [d.model_copy(update={"text": redact_pii(d.text)}) for d in kept]
        canary_docs = [d.model_copy(update={"text": redact_pii(d.text)}) for d in canary_docs]
    clean_chunks = chunk_documents(kept, spec.ingest.chunker)
    canary_chunks = chunk_documents(
        canary_docs, spec.ingest.chunker, source_channel="synthetic_test"
    )
    return await embed_into_index(clean_chunks + canary_chunks, pipeline.embedder)


def _aggregate(records: list[PrivacyRecord], config: PrivacySuiteConfig) -> list[Metric]:
    metrics: list[Metric] = []
    for condition in config.defenses:
        at = [r for r in records if r.defense == condition]
        metrics.append(
            Metric(
                suite=SUITE,
                name="leakage_rate",
                variant=f"defense={condition}",
                value=round(mean([float(r.leaked) for r in at]), 4),
            )
        )
        metrics.append(
            Metric(
                suite=SUITE,
                name="retrieval_exposure_rate",
                variant=f"defense={condition}",
                value=round(mean([float(r.retrieved) for r in at]), 4),
            )
        )
    # Which probe style extracts most, measured without the defense.
    baseline = config.defenses[0]
    for style in config.probes:
        sample = [r for r in records if r.defense == baseline and r.probe_style == style]
        metrics.append(
            Metric(
                suite=SUITE,
                name=f"leakage_rate@{style}",
                value=round(mean([float(r.leaked) for r in sample]), 4),
            )
        )
    return metrics
