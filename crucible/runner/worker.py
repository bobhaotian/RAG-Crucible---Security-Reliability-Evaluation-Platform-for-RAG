"""The evaluation worker: claim → ensure index → evaluate → persist.

A worker is a plain process polling the SQLite queue (DESIGN.md §7 — no
broker by decision; the claim is an atomic UPDATE, so multiple workers
coexist safely). Each run executes with ``fail_fast=False``: a failing suite
is recorded with its error while completed suites' results are persisted —
the run is then marked failed, but partial evidence survives.
"""

from __future__ import annotations

import asyncio
import logging
import socket

from crucible.config import RunSpec
from crucible.eval import run_eval
from crucible.ingest import load_or_build_index
from crucible.runner.models import ClaimedRun
from crucible.runner.store import ResultStore

logger = logging.getLogger(__name__)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-worker"


async def execute_run(store: ResultStore, claimed: ClaimedRun) -> None:
    try:
        spec = RunSpec.model_validate_json(claimed.spec_json)
        index = await load_or_build_index(spec)
        result = await run_eval(spec, index, fail_fast=False)
        store.save_result(claimed.id, result)
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
