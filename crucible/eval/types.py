"""Data contracts for evaluation results.

Every headline number is backed by per-item records — a metric is never
reported without the evidence to audit it. ``variant`` is how one run carries
its own comparisons (``rerank=on`` / ``rerank=off`` now; defense conditions in
Phase 4); the result store and dashboard key on it.

**Stored results are versioned.** ``EvalRunResult.schema_version`` names the
shape an artifact was written in; ``crucible.eval.migrate`` upgrades older ones
on read. The rule that governs every migration: a field an older writer did not
record reads as ``None`` — *unavailable* — and never as a value. An empty tuple
means "measured, and nothing matched"; ``None`` means "this version did not
look". Collapsing the two is how a run that never measured cross-attack
contamination comes to report zero of it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from crucible.config import RunSpec
from crucible.obs.aggregate import StageStats
from crucible.types import StrictModel

# Bump when a persisted shape changes, and add a migration in
# crucible/eval/migrate.py in the same commit. History:
#   1 — everything written before versioning existed (no schema_version key)
#   2 — schema_version + run_id on the result; attack records distinguish
#       "not recorded" from "recorded empty"
RESULT_SCHEMA_VERSION = 2

# One spelling, imported by both the eval layer and the result store. Spelled
# twice they drift, and a status one module can produce becomes a status the
# other rejects — which surfaces as a 500 from the API, not a type error.
SuiteStatus = Literal["succeeded", "failed", "skipped"]


class Metric(StrictModel):
    suite: str
    name: str  # e.g. "recall@10", "hallucination_rate"
    variant: str = ""  # e.g. "rerank=on"; "" when the metric has one condition
    value: float


class RetrievalRecord(StrictModel):
    kind: Literal["retrieval"] = "retrieval"
    qid: str
    question: str
    first_hit_rank_initial: int | None  # 1-based; None = gold never retrieved
    first_hit_rank_reranked: int | None  # None when rerank lift is off
    retrieved_initial: tuple[str, ...]  # chunk ids in rank order
    retrieved_reranked: tuple[str, ...]


class ClaimJudgment(StrictModel):
    claim: str
    supported: bool
    parse_ok: bool  # judge output parsed cleanly (False = heuristic fallback)
    cached: bool


class CitationJudgment(StrictModel):
    chunk_id: str
    supports_claim: bool


class FaithfulnessRecord(StrictModel):
    kind: Literal["faithfulness"] = "faithfulness"
    qid: str
    question: str
    answer: str
    claims: tuple[ClaimJudgment, ...]
    citations_parsed: bool  # did the generator emit usable [n] markers?
    citations: tuple[CitationJudgment, ...]  # judged parsed citations only
    # Gold answer string appears in the answer. None when the corpus labels
    # documents rather than answers (BEIR-style `gold_docs`), so there is no
    # answer string to check — scoring those as False would report a real 0.0.
    answer_match: bool | None = None


class MarkerRef(StrictModel):
    """An attacker-planted string, and which attack planted it.

    Carrying the owner (not just the string) is what lets a reader tell
    "the attack under test won" from "a different attack won instead", and
    "a competing attack on this same question" from "an attack planted on a
    different question leaked into this one".
    """

    marker: str
    attack_type: Literal["poison", "injection"]
    qid: str  # the question this marker's attack document targets


class AttackRecord(StrictModel):
    kind: Literal["attack"] = "attack"
    attack_type: Literal["poison", "injection"]  # the attack this trial tests
    qid: str
    question: str
    defense: str  # the condition this pass ran under: none|prompt_isolation|injection_filter
    retrieved: bool  # the attack chunk reached the prompt context
    succeeded: bool  # poison: false value echoed; injection: token obeyed
    # `succeeded` attributes one attack. One index carries every attack document,
    # so a trial can be compromised by a *different* attack than the one under
    # test — invisible to `succeeded`. These record that:
    # The three fields below are `None` when the writer did not record them
    # (schema 1). `None` is not `""` / `()` / `False`: an empty marker tuple
    # says the answer was checked and carried nothing, while `None` says this
    # run never checked. Every new write sets all three.
    own_marker: str | None = None  # the string `succeeded` was scored on
    # Injection only: was the shipped filter written against this phrasing?
    # Splitting the rate by this is what separates "the defense works" from
    # "the defense recognises the two payloads it was built for". `None` on a
    # poison record means not applicable; on an injection record it means the
    # writer predates families.
    attack_family: str | None = None
    compromised: bool = False  # the answer carries any attacker-planted marker
    matched_markers: tuple[MarkerRef, ...] | None = None  # planted markers in the answer
    abstained: bool | None = None
    answer: str

    @property
    def foreign_markers(self) -> tuple[MarkerRef, ...] | None:
        """Markers in the answer that belong to some attack other than this one.

        ``None`` when the marker scan was not recorded — returning an empty
        tuple there would report "no other attack won" about a run that never
        asked.
        """
        if self.matched_markers is None or self.own_marker is None:
            return None
        return tuple(m for m in self.matched_markers if m.marker != self.own_marker)

    @property
    def competing_markers(self) -> tuple[MarkerRef, ...] | None:
        """Foreign markers from the *other* attack on this same question."""
        foreign = self.foreign_markers
        return None if foreign is None else tuple(m for m in foreign if m.qid == self.qid)

    @property
    def cross_question_markers(self) -> tuple[MarkerRef, ...] | None:
        """Foreign markers planted on a *different* question — true bleed-through."""
        foreign = self.foreign_markers
        return None if foreign is None else tuple(m for m in foreign if m.qid != self.qid)


class PrivacyRecord(StrictModel):
    kind: Literal["canary_probe"] = "canary_probe"
    canary_id: str
    canary_kind: str  # email | api_key | phone
    probe_style: str  # direct | indirect | paraphrase
    defense: str  # none | pii_filter
    retrieved: bool  # the canary chunk reached the prompt context (retrieval exposure)
    leaked: bool  # the secret appeared verbatim in the answer (generation leakage)
    answer: str


class CleanDefenseRecord(StrictModel):
    """Clean-traffic control used to expose a defense's refusal cost."""

    kind: Literal["clean_defense"] = "clean_defense"
    qid: str
    question: str
    defense: str
    abstained: bool
    answer_match: bool | None
    answer: str


EvalRecord = Annotated[
    RetrievalRecord | FaithfulnessRecord | AttackRecord | PrivacyRecord | CleanDefenseRecord,
    Field(discriminator="kind"),
]


class SuiteResult(StrictModel):
    suite: str
    status: SuiteStatus = "succeeded"
    error: str | None = None
    metrics: tuple[Metric, ...]
    records: tuple[EvalRecord, ...]


class EvalRunResult(StrictModel):
    """Everything one evaluation run produced. Persisted as results.json in
    Phase 2; the Phase 3 result store decomposes the same model into tables.

    Read persisted JSON through ``crucible.eval.migrate.load_result_json``
    rather than ``model_validate_json`` — the latter is strict by design and
    will reject any artifact written before the current schema version.
    """

    # Always the current version on a new object; older artifacts are upgraded
    # to it by the migration chain before they are ever validated.
    schema_version: int = RESULT_SCHEMA_VERSION
    # `None` = the writer did not record one (schema 1). Present on every new
    # write, so an artifact identifies itself without its directory name.
    run_id: str | None = None
    name: str
    spec_hash: str
    seed: int
    started_at: str  # ISO-8601 UTC
    finished_at: str
    suites: tuple[SuiteResult, ...]
    stage_stats: tuple[StageStats, ...]
    spec: RunSpec  # the full spec, so the run is reproducible from this file

    def metric(self, suite: str, name: str, variant: str = "") -> float | None:
        for suite_result in self.suites:
            if suite_result.suite != suite:
                continue
            for metric in suite_result.metrics:
                if metric.name == name and metric.variant == variant:
                    return metric.value
        return None
