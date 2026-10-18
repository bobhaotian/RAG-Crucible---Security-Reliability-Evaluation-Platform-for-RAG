"""Typed rows and views over the result store — no raw dicts cross out of
``rag_crucible.runner``."""

from __future__ import annotations

from typing import Literal

from rag_crucible.eval.types import Metric, SuiteStatus
from rag_crucible.obs.aggregate import StageStats
from rag_crucible.types import StrictModel

RunStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class RunRow(StrictModel):
    id: str
    name: str
    spec_hash: str
    status: RunStatus
    error: str | None = None
    claimed_by: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ClaimedRun(StrictModel):
    id: str
    name: str
    spec_json: str


class SuiteSummary(StrictModel):
    suite: str
    # Same alias the eval layer writes with. Spelled separately, a status one
    # side can produce becomes one the other rejects, and the API 500s.
    status: SuiteStatus
    error: str | None = None
    metric_count: int  # every metric emitted, measured or not; their states are in metrics
    record_count: int


class RunResults(StrictModel):
    """Everything the API returns for GET /runs/{id}/results."""

    run: RunRow
    suites: list[SuiteSummary]
    metrics: list[Metric]
    stage_stats: list[StageStats]


class RecordRow(StrictModel):
    id: int
    suite: str
    kind: str
    payload_json: str
    # The result schema the payload was serialised at. None = stored before
    # the store recorded it, by a writer at schema 5 or older; which one is
    # unknown, so it is not guessed.
    payload_schema: int | None = None
