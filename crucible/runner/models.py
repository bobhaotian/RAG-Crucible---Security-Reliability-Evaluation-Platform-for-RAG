"""Typed rows and views over the result store — no raw dicts cross out of
``crucible.runner``."""

from __future__ import annotations

from typing import Literal

from crucible.eval.types import Metric
from crucible.obs.aggregate import StageStats
from crucible.types import StrictModel

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
    status: Literal["succeeded", "failed"]
    error: str | None = None
    metric_count: int
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
