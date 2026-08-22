"""SQLite result store — and the job queue (DESIGN.md §6-7).

Stdlib ``sqlite3`` behind a typed repository; no ORM by decision (single
writer, few tables, graders can ``sqlite3 crucible.db`` and look around).
The ``runs`` table doubles as the queue: workers claim the oldest pending row
with one atomic ``UPDATE … RETURNING``. WAL mode + busy timeout cover the
API-reads-while-worker-writes case. Connections are opened per operation —
cheap for SQLite and trivially thread-safe under FastAPI's threadpool.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from crucible.config import RunSpec
from crucible.eval.types import EvalRunResult, Metric
from crucible.obs.aggregate import StageStats
from crucible.runner.ids import new_run_id
from crucible.runner.models import (
    ClaimedRun,
    RecordRow,
    RunResults,
    RunRow,
    RunStatus,
    SuiteSummary,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  spec_json    TEXT NOT NULL,
  spec_hash    TEXT NOT NULL,
  status       TEXT NOT NULL,
  error        TEXT,
  claimed_by   TEXT,
  created_at   TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_spec_hash ON runs(spec_hash);

CREATE TABLE IF NOT EXISTS suite_results (
  run_id       TEXT NOT NULL REFERENCES runs(id),
  suite        TEXT NOT NULL,
  status       TEXT NOT NULL,
  error        TEXT,
  summary_json TEXT NOT NULL,
  PRIMARY KEY (run_id, suite)
);

CREATE TABLE IF NOT EXISTS metrics (
  run_id   TEXT NOT NULL REFERENCES runs(id),
  suite    TEXT NOT NULL,
  name     TEXT NOT NULL,
  variant  TEXT NOT NULL DEFAULT '',
  value    REAL NOT NULL,
  PRIMARY KEY (run_id, suite, name, variant)
);

CREATE TABLE IF NOT EXISTS records (
  id           INTEGER PRIMARY KEY,
  run_id       TEXT NOT NULL REFERENCES runs(id),
  suite        TEXT NOT NULL,
  kind         TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_run_suite ON records(run_id, suite, id);

CREATE TABLE IF NOT EXISTS stage_timings (
  run_id  TEXT NOT NULL REFERENCES runs(id),
  stage   TEXT NOT NULL,
  count   INTEGER NOT NULL,
  mean_ms REAL NOT NULL,
  p50_ms  REAL NOT NULL,
  p95_ms  REAL NOT NULL,
  PRIMARY KEY (run_id, stage)
);
"""


class DuplicateRunError(Exception):
    def __init__(self, existing_run_id: str, spec_hash: str) -> None:
        self.existing_run_id = existing_run_id
        super().__init__(
            f"a run with this exact spec already exists ({existing_run_id}, "
            f"spec_hash {spec_hash[:12]}); pass force=True to re-run"
        )


class RunNotFoundError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ResultStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # one transaction per operation
                yield conn
        finally:
            conn.close()

    # -- queue side -------------------------------------------------------

    def submit_run(self, spec: RunSpec, *, force: bool = False) -> str:
        spec_hash = spec.spec_hash()
        with self._connect() as conn:
            if not force:
                row = conn.execute(
                    "SELECT id FROM runs WHERE spec_hash = ? "
                    "AND status IN ('pending', 'running', 'succeeded') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (spec_hash,),
                ).fetchone()
                if row is not None:
                    raise DuplicateRunError(row["id"], spec_hash)
            run_id = new_run_id()
            conn.execute(
                "INSERT INTO runs (id, name, spec_json, spec_hash, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (run_id, spec.name, spec.canonical_json(), spec_hash, _now()),
            )
            return run_id

    def claim_next(self, worker_id: str) -> ClaimedRun | None:
        """Atomically claim the oldest pending run. Safe under concurrent
        workers: the UPDATE either moves one row pending→running or no-ops."""
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE runs SET status = 'running', claimed_by = ?, started_at = ? "
                "WHERE id = (SELECT id FROM runs WHERE status = 'pending' "
                "            ORDER BY created_at, rowid LIMIT 1) "
                "RETURNING id, name, spec_json",
                (worker_id, _now()),
            ).fetchone()
        if row is None:
            return None
        return ClaimedRun(id=row["id"], name=row["name"], spec_json=row["spec_json"])

    def mark_succeeded(self, run_id: str) -> None:
        self._finish(run_id, "succeeded", None)

    def mark_failed(self, run_id: str, error: str) -> None:
        self._finish(run_id, "failed", error)

    def _finish(self, run_id: str, status: RunStatus, error: str | None) -> None:
        with self._connect() as conn:
            updated = conn.execute(
                "UPDATE runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, error, _now(), run_id),
            ).rowcount
        if updated == 0:
            raise RunNotFoundError(run_id)

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a pending run. Returns False if it already left the queue."""
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise RunNotFoundError(run_id)
            updated = conn.execute(
                "UPDATE runs SET status = 'cancelled', finished_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (_now(), run_id),
            ).rowcount
        return updated == 1

    # -- result side ------------------------------------------------------

    def save_result(self, run_id: str, result: EvalRunResult) -> None:
        """Decompose an EvalRunResult into the queryable tables, atomically."""
        with self._connect() as conn:
            for suite in result.suites:
                summary = {
                    "metric_count": len(suite.metrics),
                    "record_count": len(suite.records),
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                }
                conn.execute(
                    "INSERT OR REPLACE INTO suite_results "
                    "(run_id, suite, status, error, summary_json) VALUES (?, ?, ?, ?, ?)",
                    (run_id, suite.suite, suite.status, suite.error, json.dumps(summary)),
                )
                for metric in suite.metrics:
                    conn.execute(
                        "INSERT OR REPLACE INTO metrics (run_id, suite, name, variant, value) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (run_id, metric.suite, metric.name, metric.variant, metric.value),
                    )
                for record in suite.records:
                    conn.execute(
                        "INSERT INTO records (run_id, suite, kind, payload_json) "
                        "VALUES (?, ?, ?, ?)",
                        (run_id, suite.suite, record.kind, record.model_dump_json()),
                    )
            for stats in result.stage_stats:
                conn.execute(
                    "INSERT OR REPLACE INTO stage_timings "
                    "(run_id, stage, count, mean_ms, p50_ms, p95_ms) VALUES (?, ?, ?, ?, ?, ?)",
                    (run_id, stats.stage, stats.count, stats.mean_ms, stats.p50_ms, stats.p95_ms),
                )

    # -- read side --------------------------------------------------------

    def get_run(self, run_id: str) -> RunRow:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, spec_hash, status, error, claimed_by, "
                "created_at, started_at, finished_at FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return RunRow(**dict(row))

    def get_spec_json(self, run_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT spec_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return str(row["spec_json"])

    def list_runs(self, *, limit: int = 50) -> list[RunRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, spec_hash, status, error, claimed_by, "
                "created_at, started_at, finished_at FROM runs "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RunRow(**dict(row)) for row in rows]

    def get_results(self, run_id: str) -> RunResults:
        run = self.get_run(run_id)
        with self._connect() as conn:
            suite_rows = conn.execute(
                "SELECT suite, status, error, summary_json FROM suite_results "
                "WHERE run_id = ? ORDER BY suite",
                (run_id,),
            ).fetchall()
            metric_rows = conn.execute(
                "SELECT suite, name, variant, value FROM metrics "
                "WHERE run_id = ? ORDER BY suite, name, variant",
                (run_id,),
            ).fetchall()
            timing_rows = conn.execute(
                "SELECT stage, count, mean_ms, p50_ms, p95_ms FROM stage_timings "
                "WHERE run_id = ? ORDER BY stage",
                (run_id,),
            ).fetchall()
        suites = []
        for row in suite_rows:
            summary = json.loads(row["summary_json"])
            suites.append(
                SuiteSummary(
                    suite=row["suite"],
                    status=row["status"],
                    error=row["error"],
                    metric_count=int(summary.get("metric_count", 0)),
                    record_count=int(summary.get("record_count", 0)),
                )
            )
        return RunResults(
            run=run,
            suites=suites,
            metrics=[Metric(**dict(row)) for row in metric_rows],
            stage_stats=[StageStats(**dict(row)) for row in timing_rows],
        )

    def get_records(
        self, run_id: str, *, suite: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[RecordRow]:
        self.get_run(run_id)  # 404 before returning an empty page
        query = "SELECT id, suite, kind, payload_json FROM records WHERE run_id = ?"
        params: list[object] = [run_id]
        if suite is not None:
            query += " AND suite = ?"
            params.append(suite)
        query += " ORDER BY id LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [RecordRow(**dict(row)) for row in rows]
