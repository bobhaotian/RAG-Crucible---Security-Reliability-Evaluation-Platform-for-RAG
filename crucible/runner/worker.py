"""The evaluation worker: claim → ensure index → evaluate → persist + report.

A worker is a plain process polling the SQLite queue (DESIGN.md §7 — no
broker by decision; the claim is an atomic UPDATE, so multiple workers
coexist safely). Each run executes with ``fail_fast=False``: a failing suite
is recorded with its error while completed suites' results are persisted —
the run is then marked failed, but partial evidence survives in both SQLite
and the shareable report directory.
"""

from __future__ import annotations

import asyncio
import logging
import socket

from crucible.config import RunSpec
from crucible.eval import run_eval
from crucible.eval.report import write_report
from crucible.ingest import load_or_build_index
from crucible.paths import submitted_run_results_dir
from crucible.runner.models import ClaimedRun, RunRow
from crucible.runner.store import ResultStore

logger = logging.getLogger(__name__)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-worker"


async def execute_run(store: ResultStore, claimed: ClaimedRun) -> None:
    try:
        spec = RunSpec.model_validate_json(claimed.spec_json)
        index = await load_or_build_index(spec)
        result = await run_eval(spec, index, fail_fast=False)

        # SQLite is the dashboard/query source of truth. Once it has the full
        # result, render the same portable artifacts as `crucible eval`. A
        # run-specific directory prevents forced reruns from overwriting one
        # another. Report generation is part of successful job completion: if
        # it fails, the already-persisted database evidence survives and the
        # run is marked failed with an actionable error.
        store.save_result(claimed.id, result)
        report_dir = submitted_run_results_dir(spec.name, claimed.id)
        written = write_report(result, report_dir)
        logger.info(
            "run %s wrote %d report artifact(s) to %s",
            claimed.id,
            len(written),
            report_dir,
        )

        failed = [s for s in result.suites if s.status == "failed"]
        if failed:
            errors = "; ".join(f"{s.suite}: {s.error}" for s in failed)
            store.mark_failed(claimed.id, errors)
            logger.warning("run %s failed: %s", claimed.id, errors)
        else:
            store.mark_succeeded(claimed.id)
            logger.info("run %s succeeded", claimed.id)
    except Exception as exc:  # the worker must survive any single run crashing
        store.mark_failed(claimed.id, f"{type(exc).__name__}: {exc}")
        logger.exception("run %s crashed", claimed.id)


async def execute_or_wait_for_run(
    store: ResultStore,
    run_id: str,
    *,
    worker_id: str | None = None,
    poll_interval_s: float = 0.25,
) -> RunRow:
    """Execute a particular queued run and wait for its terminal status.

    Normally this process claims and executes the run itself. If a background
    worker wins the atomic claim, wait for that worker instead, so one CLI
    command still means "submit and complete" without double execution.
    """
    wid = worker_id or f"{default_worker_id()}-inline"
    while True:
        row = store.get_run(run_id)
        if row.status in ("succeeded", "failed", "cancelled"):
            return row
        if row.status == "pending":
            claimed = store.claim_run(run_id, wid)
            if claimed is not None:
                await execute_run(store, claimed)
                continue
        await asyncio.sleep(poll_interval_s)


async def worker_loop(
    store: ResultStore,
    *,
    worker_id: str | None = None,
    poll_interval_s: float = 1.0,
    drain: bool = False,
) -> int:
    """Process runs until cancelled; with ``drain=True`` return once the
    queue is empty (used by tests and one-shot invocations). Returns the
    number of runs processed."""
    wid = worker_id or default_worker_id()
    processed = 0
    while True:
        claimed = store.claim_next(wid)
        if claimed is None:
            if drain:
                return processed
            await asyncio.sleep(poll_interval_s)
            continue
        logger.info("worker %s claimed run %s (%s)", wid, claimed.id, claimed.name)
        await execute_run(store, claimed)
        processed += 1
