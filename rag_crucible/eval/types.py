"""Data contracts for evaluation results.

Every headline number is backed by per-item records — a metric is never
reported without the evidence to audit it. ``variant`` is how one run carries
its own comparisons (``rerank=on`` / ``rerank=off`` now; defense conditions in
Phase 4); the result store and dashboard key on it.

**Stored results are versioned.** ``EvalRunResult.schema_version`` names the
shape an artifact was written in; ``rag_crucible.eval.migrate`` upgrades older ones
on read. The rule that governs every migration: a field an older writer did not
record reads as ``None`` — *unavailable* — and never as a value. An empty tuple
means "measured, and nothing matched"; ``None`` means "this version did not
look". Collapsing the two is how a run that never measured cross-attack
contamination comes to report zero of it.

**A metric says whether it was measured.** ``Metric.state`` is ``"measured"``
exactly when ``value`` carries a number; every other state carries a
``reason`` and no value. So a metric that could not be computed can be
emitted with its reason instead of being omitted or written as 0.0, and "this
run did not measure it" stays distinct from "this run measured zero".
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import Field, field_serializer, model_validator

from rag_crucible.config import RunSpec
from rag_crucible.ingest.build import IngestReport
from rag_crucible.obs.aggregate import StageStats
from rag_crucible.types import StrictModel

# Bump when a persisted shape changes, and add a migration in
# rag_crucible/eval/migrate.py in the same commit. History:
#   1 — everything written before versioning existed (no schema_version key)
#   2 — schema_version + run_id on the result; attack records distinguish
#       "not recorded" from "recorded empty"
#   3 — ingestion audit embedded in every newly written result
#   4 — corpus and QA content digests preserved in the embedded spec
#   5 — per-chunk clean-defense screening evidence
#   6 — every metric carries a state (and a reason when it was not measured)
RESULT_SCHEMA_VERSION = 6

# One spelling, imported by both the eval layer and the result store. Spelled
# twice they drift, and a status one module can produce becomes a status the
# other rejects — which surfaces as a 500 from the API, not a type error.
SuiteStatus = Literal["succeeded", "failed", "skipped"]


# Why a metric does or does not carry a number. Only "measured" does, and a
# true zero is a measured 0.0. The rest say why there is no value: the data
# cannot support it (no labels), it does not apply to this configuration, it
# was deliberately not run, it failed, or it is undefined at any sample size
# (a relative reduction against a zero baseline).
MetricState = Literal[
    "measured", "unsupported", "inapplicable", "skipped", "error", "not_estimable"
]


class Metric(StrictModel):
    suite: str
    name: str  # e.g. "recall@10", "hallucination_rate"
    variant: str = ""  # e.g. "rerank=on"; "" when the metric has one condition
    value: float | None  # None exactly when state is not "measured"
    state: MetricState = "measured"
    reason: str | None = None  # required, non-empty, whenever state is not "measured"

    @model_validator(mode="after")
    def _value_present_exactly_when_measured(self) -> Metric:
        if self.state == "measured":
            if self.value is None:
                raise ValueError("a measured metric needs a value; give another state and a reason")
            # Not a measurement either. SQLite stores NaN as NULL and JSON
            # writes NaN and inf as null, so a non-finite "measured" value
            # would come back from storage as a measured metric with no value.
            if not math.isfinite(self.value):
                raise ValueError(f"a measured value must be finite, got {self.value}")
            return self
        if self.value is not None:
            raise ValueError(f"a {self.state} metric carries no value, got {self.value}")
        if not self.reason or not self.reason.strip():
            raise ValueError(f"a {self.state} metric needs a reason")
        return self

    @property
    def measured_value(self) -> float:
        """The value, for code that can only show a number.

        Raises ``MetricNotMeasuredError`` when there is none, so a metric that
        was not measured fails loudly there instead of being drawn as one.
        """
        if self.value is None:  # exactly the not-measured states, by the validator
            raise MetricNotMeasuredError(self)
        return self.value


class MetricNotMeasuredError(Exception):
    """The metric exists, but carries no value: it was not measured.

    Raised by ``EvalRunResult.metric``, whose ``None`` already means "the run
    emitted no such metric". A metric that is present but unmeasured is a
    third answer, and returning ``None`` for it would merge the two.
    """

    def __init__(self, metric: Metric) -> None:
        self.metric = metric
        self.state = metric.state
        self.reason = metric.reason
        variant = f" [{metric.variant}]" if metric.variant else ""
        super().__init__(
            f"{metric.suite}/{metric.name}{variant} is {metric.state}: {metric.reason}"
        )


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
    # `compromised` is the boolean view of the same scan `matched_markers`
    # details — a live run sets both from one pass — so it is unavailable on
    # exactly the runs that scan is unavailable on. Defaulting it to False
    # would say "this trial was not compromised" about a trial nobody scanned,
    # which is the invented zero the three fields above exist to avoid.
    compromised: bool | None = None  # the answer carries any attacker-planted marker
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


class CleanScreenRecord(StrictModel):
    """Whether a defense would delete one legitimate corpus chunk."""

    kind: Literal["clean_screen"] = "clean_screen"
    defense: str
    chunk_id: str
    source: str
    screened: bool
    reason: str | None = None


EvalRecord = Annotated[
    RetrievalRecord
    | FaithfulnessRecord
    | AttackRecord
    | PrivacyRecord
    | CleanDefenseRecord
    | CleanScreenRecord,
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

    Read persisted JSON through ``rag_crucible.eval.migrate.load_result_json``
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
    # Exact canonical spec text used to mint spec_hash. Historical RunSpec
    # models gain defaults over time; this preserves the writer's identity.
    spec_identity_json: str | None = None
    seed: int
    started_at: str  # ISO-8601 UTC
    finished_at: str
    suites: tuple[SuiteResult, ...]
    stage_stats: tuple[StageStats, ...]
    # None only when reading an artifact created before schema 3.
    ingestion: IngestReport | None = None
    spec: RunSpec  # the full spec, so the run is reproducible from this file

    @model_validator(mode="after")
    def _identity_receipt_matches_hash(self) -> EvalRunResult:
        if self.spec_identity_json is not None:
            actual = hashlib.sha256(self.spec_identity_json.encode()).hexdigest()
            if actual != self.spec_hash:
                raise ValueError("spec_identity_json does not reproduce spec_hash")
        return self

    @field_serializer("spec")
    def _serialize_spec_with_original_identity(self, spec: RunSpec) -> dict[str, object]:
        """Keep historical specs byte-for-byte canonical when re-serialised.

        Parsing an old spec through today's ``RunSpec`` adds defaults that did
        not exist when the run was created. The identity receipt records the
        exact canonical object that minted ``spec_hash``; using it here keeps
        a read/write round trip from silently backdating those options.
        """
        if self.spec_identity_json is not None:
            identity = json.loads(self.spec_identity_json)
            if not isinstance(identity, dict):  # guarded by the hash validator
                raise ValueError("spec_identity_json must encode an object")
            return identity
        return spec.model_dump(mode="json")

    def metric_entry(self, suite: str, name: str, variant: str = "") -> Metric | None:
        """The metric itself, whatever its state; ``None`` when it was not emitted."""
        for suite_result in self.suites:
            if suite_result.suite != suite:
                continue
            for metric in suite_result.metrics:
                if metric.name == name and metric.variant == variant:
                    return metric
        return None

    def metric(self, suite: str, name: str, variant: str = "") -> float | None:
        """A measured value, or ``None`` when the run emitted no such metric.

        Raises ``MetricNotMeasuredError`` when the metric is present but not
        measured, so that ``None`` keeps meaning only "absent". Use
        ``metric_entry`` to read the state and reason instead.
        """
        entry = self.metric_entry(suite, name, variant)
        return None if entry is None else entry.measured_value
