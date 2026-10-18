"""SQLite result store — and the job queue (DESIGN.md §6-7).

Stdlib ``sqlite3`` behind a typed repository; no ORM by decision (single
writer, few tables, graders can ``sqlite3 crucible.db`` and look around).
The ``runs`` table doubles as the queue: workers claim the oldest pending row
with one atomic ``UPDATE … RETURNING``. WAL mode + busy timeout cover the
API-reads-while-worker-writes case. Connections are opened per operation —
cheap for SQLite and trivially thread-safe under FastAPI's threadpool.

The store is versioned in SQLite's ``PRAGMA user_version``. Opening one runs
whatever migrations it is behind on, in a single transaction, and refuses a
store written by a newer version. A fresh store is created at the latest
version directly. Record payloads carry the result schema they were
serialised at (``records.payload_schema``), so they can be migrated on read
like a ``results.json`` is.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from rag_crucible.config import RunSpec
from rag_crucible.eval.types import RESULT_SCHEMA_VERSION, EvalRunResult, Metric
from rag_crucible.obs.aggregate import StageStats
from rag_crucible.runner.ids import new_run_id
from rag_crucible.runner.models import (
    ClaimedRun,
    RecordRow,
    RunResults,
    RunRow,
    RunStatus,
    SuiteSummary,
)

# The latest schema, one statement per entry: ``_migrate`` runs them inside a
# transaction it opened, and ``executescript`` would commit that early. A fresh
# store is created from this directly, at STORE_SCHEMA_VERSION.
_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE runs (
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
    )
    """,
    "CREATE INDEX idx_runs_status ON runs(status, created_at)",
    "CREATE INDEX idx_runs_spec_hash ON runs(spec_hash)",
    """
    CREATE TABLE suite_results (
      run_id       TEXT NOT NULL REFERENCES runs(id),
      suite        TEXT NOT NULL,
      status       TEXT NOT NULL,
      error        TEXT,
      summary_json TEXT NOT NULL,
      PRIMARY KEY (run_id, suite)
    )
    """,
    """
    CREATE TABLE metrics (
      run_id   TEXT NOT NULL REFERENCES runs(id),
      suite    TEXT NOT NULL,
      name     TEXT NOT NULL,
      variant  TEXT NOT NULL DEFAULT '',
      value    REAL,
      state    TEXT NOT NULL DEFAULT 'measured',
      reason   TEXT,
      PRIMARY KEY (run_id, suite, name, variant),
      CHECK ((value IS NULL) = (state != 'measured'))
    )
    """,
    """
    CREATE TABLE records (
      id             INTEGER PRIMARY KEY,
      run_id         TEXT NOT NULL REFERENCES runs(id),
      suite          TEXT NOT NULL,
      kind           TEXT NOT NULL,
      payload_json   TEXT NOT NULL,
      payload_schema INTEGER
    )
    """,
    "CREATE INDEX idx_records_run_suite ON records(run_id, suite, id)",
    """
    CREATE TABLE stage_timings (
      run_id  TEXT NOT NULL REFERENCES runs(id),
      stage   TEXT NOT NULL,
      count   INTEGER NOT NULL,
      mean_ms REAL NOT NULL,
      p50_ms  REAL NOT NULL,
      p95_ms  REAL NOT NULL,
      PRIMARY KEY (run_id, stage)
    )
    """,
)

# Ordered migrations, keyed on ``PRAGMA user_version``: _MIGRATIONS[n] takes a
# store at version n to n + 1. Version 0 is every store created before
# versioning existed, and it is exactly the original DDL, which never changed
# before this list was added. The steps are history: never edit one, append a
# new step and keep _SCHEMA equal to where the steps end, which
# test_a_migrated_store_has_the_shape_of_a_fresh_one checks.
#
# A nullable, unconstrained column is added in place with ``ALTER TABLE ...
# ADD COLUMN``. That covers the per-metric statistics planned next (B2: n,
# n_clusters, ci_low, ci_high, method), so they are one more step of plain
# ADD COLUMNs and need no second rebuild. What SQLite cannot alter in place,
# such as dropping a NOT NULL, rebuilds the table instead: create the new
# shape, copy every row, drop the old table, rename the new one into place.
_MIGRATIONS: tuple[tuple[str, ...], ...] = (
    # 0 -> 1. metrics.value loses its NOT NULL, because a metric that was not
    # measured has no value and says why in state and reason. Every existing
    # row was written when a metric could only be measured, so it is copied
    # as 'measured'. records gains payload_schema; existing rows keep NULL,
    # because their writers did not record which result schema they used.
    (
        """
        CREATE TABLE metrics_v1 (
          run_id   TEXT NOT NULL REFERENCES runs(id),
          suite    TEXT NOT NULL,
          name     TEXT NOT NULL,
          variant  TEXT NOT NULL DEFAULT '',
          value    REAL,
          state    TEXT NOT NULL DEFAULT 'measured',
          reason   TEXT,
          PRIMARY KEY (run_id, suite, name, variant),
          CHECK ((value IS NULL) = (state != 'measured'))
        )
        """,
        "INSERT INTO metrics_v1 (run_id, suite, name, variant, value, state, reason) "
        "SELECT run_id, suite, name, variant, value, 'measured', NULL FROM metrics",
        "DROP TABLE metrics",
        "ALTER TABLE metrics_v1 RENAME TO metrics",
        "ALTER TABLE records ADD COLUMN payload_schema INTEGER",
    ),
)
STORE_SCHEMA_VERSION = len(_MIGRATIONS)


class StoreSchemaError(Exception):
    """The database cannot be opened as a result store by this version."""


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
        self._migrate()

    def _migrate(self) -> None:
        """Bring the store to STORE_SCHEMA_VERSION, creating it there if empty.

        Every step runs in one transaction, so a failure leaves the store as it
        was. ``BEGIN IMMEDIATE`` takes the write lock before the version is
        read again, so an API and a worker that open an old store together
        migrate it once: the second waits, then finds nothing left to do.
        """
        # isolation_level=None: the sqlite3 module opens and commits no
        # transaction of its own, so the one below is the only one. Foreign
        # keys stay off, the default, as SQLite's table-rebuild procedure
        # requires; rows are copied as they are.
        conn = sqlite3.connect(self._path, timeout=10.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            if self._version(conn) == STORE_SCHEMA_VERSION:
                return  # the common case, and it takes no write lock
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = self._version(conn)
                if version > STORE_SCHEMA_VERSION:
                    raise StoreSchemaError(
                        f"{self._path} was written by a newer version (store schema "
                        f"{version}; this build reads up to {STORE_SCHEMA_VERSION}). "
                        "Upgrade rag-crucible to open it."
                    )
                empty = (
                    conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'").fetchone()
                    is None
                )
                steps = _SCHEMA if empty else tuple(s for m in _MIGRATIONS[version:] for s in m)
                for statement in steps:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @staticmethod
    def _version(conn: sqlite3.Connection) -> int:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])

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
        spec = spec.with_content_digests()
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

    def claim_run(self, run_id: str, worker_id: str) -> ClaimedRun | None:
        """Atomically claim one specific pending run.

        The synchronous CLI submission path uses this so it executes the run
        it just created without draining older jobs from the shared queue. A
        concurrent background worker may win the claim; in that case this
        returns ``None`` and the CLI waits for that worker to finish.
        """
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE runs SET status = 'running', claimed_by = ?, started_at = ? "
                "WHERE id = ? AND status = 'pending' "
                "RETURNING id, name, spec_json",
                (worker_id, _now(), run_id),
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
                        "INSERT OR REPLACE INTO metrics "
                        "(run_id, suite, name, variant, value, state, reason) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            metric.suite,
                            metric.name,
                            metric.variant,
                            metric.value,
                            metric.state,
                            metric.reason,
                        ),
                    )
                for record in suite.records:
                    # Serialised by today's models, whatever version the result
                    # was read from, so the payload is at the current schema.
                    conn.execute(
                        "INSERT INTO records (run_id, suite, kind, payload_json, payload_schema) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            run_id,
                            suite.suite,
                            record.kind,
                            record.model_dump_json(),
                            RESULT_SCHEMA_VERSION,
                        ),
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
                "SELECT suite, name, variant, value, state, reason FROM metrics "
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
        query = "SELECT id, suite, kind, payload_json, payload_schema FROM records WHERE run_id = ?"
        params: list[object] = [run_id]
        if suite is not None:
            query += " AND suite = ?"
            params.append(suite)
        query += " ORDER BY id LIMIT ? OFFSET ?"
        params += [limit, offset]
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [RecordRow(**dict(row)) for row in rows]
