"""Opening a result store written before the store was versioned.

The fixture is a store exactly as it was written before migrations existed.
Its DDL and INSERT statements are copied verbatim from
``rag_crucible/runner/store.py`` at 090e7d8, and its rows are a committed run,
so the migration is tested against the shape real stores are in, including a
true zero that has to survive as a measured 0.0.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, get_args

import pytest

import rag_crucible.runner.store as store_module
from rag_crucible.eval.types import EvalRunResult, Metric, MetricState, SuiteResult
from rag_crucible.runner import STORE_SCHEMA_VERSION, ResultStore, StoreSchemaError

from .test_store import _spec

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_RUN = REPO_ROOT / "results/demo-local-baseline/01M19XHZST1GCPPPGTFQR9KW81/results.json"

# Verbatim from store.py at 090e7d8. Never update this to match the current
# DDL: it is what stores in the wild were created with.
LEGACY_DDL = """
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

LEGACY_METRIC_INSERT = (
    "INSERT OR REPLACE INTO metrics (run_id, suite, name, variant, value) VALUES (?, ?, ?, ?, ?)"
)


def _legacy_store(path: Path) -> tuple[str, dict[str, Any]]:
    """Write a version-0 store holding one committed run, the way the old
    ``ResultStore`` did; return the run id and the run's raw JSON."""
    raw: dict[str, Any] = json.loads(LEGACY_RUN.read_text(encoding="utf-8"))
    run_id = LEGACY_RUN.parent.name
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(LEGACY_DDL)
    with conn:
        conn.execute(
            "INSERT INTO runs (id, name, spec_json, spec_hash, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (
                run_id,
                raw["name"],
                json.dumps(raw["spec"], sort_keys=True, separators=(",", ":")),
                raw["spec_hash"],
                raw["started_at"],
            ),
        )
        for suite in raw["suites"]:
            summary = {
                "metric_count": len(suite["metrics"]),
                "record_count": len(suite["records"]),
                "started_at": raw["started_at"],
                "finished_at": raw["finished_at"],
            }
            conn.execute(
                "INSERT OR REPLACE INTO suite_results "
                "(run_id, suite, status, error, summary_json) VALUES (?, ?, ?, ?, ?)",
                (run_id, suite["suite"], suite["status"], suite["error"], json.dumps(summary)),
            )
            for m in suite["metrics"]:
                conn.execute(
                    LEGACY_METRIC_INSERT, (run_id, m["suite"], m["name"], m["variant"], m["value"])
                )
            for record in suite["records"]:
                conn.execute(
                    "INSERT INTO records (run_id, suite, kind, payload_json) VALUES (?, ?, ?, ?)",
                    (run_id, suite["suite"], record["kind"], json.dumps(record)),
                )
        for s in raw["stage_stats"]:
            conn.execute(
                "INSERT OR REPLACE INTO stage_timings "
                "(run_id, stage, count, mean_ms, p50_ms, p95_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, s["stage"], s["count"], s["mean_ms"], s["p50_ms"], s["p95_ms"]),
            )
        conn.execute(
            "UPDATE runs SET status = 'succeeded', finished_at = ? WHERE id = ?",
            (raw["finished_at"], run_id),
        )
    conn.close()
    return run_id, raw


def _rows(path: Path, sql: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return [tuple(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _write(path: Path, sql: str) -> None:
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute(sql)
    finally:
        conn.close()


def _user_version(path: Path) -> int:
    return int(_rows(path, "PRAGMA user_version")[0][0])


def _normalised_sql(sql: str) -> str:
    """A table's CREATE statement with whitespace collapsed, and without the
    quotes SQLite adds when a rebuilt table is renamed into place or the line
    break it keeps before a column ADD COLUMN appended."""
    sql = re.sub(r"\s+", " ", sql).strip()
    sql = re.sub(r"\(\s+", "(", re.sub(r"\s+([),])", r"\1", sql))
    return re.sub(r'^CREATE TABLE "(\w+)"', r"CREATE TABLE \1", sql)


def _shape(path: Path) -> dict[str, Any]:
    """Every table's columns, indexes and CREATE statement (so its CHECKs), as
    SQLite reports them."""
    shape: dict[str, Any] = {}
    tables = _rows(path, "SELECT name, sql FROM sqlite_master WHERE type = 'table'")
    for table, sql in tables:
        indexes = {
            name: (unique, origin, _rows(path, f"PRAGMA index_info({name})"))
            for _, name, unique, origin, _ in _rows(path, f"PRAGMA index_list({table})")
        }
        shape[table] = {
            "columns": _rows(path, f"PRAGMA table_xinfo({table})"),
            "indexes": indexes,
            "sql": _normalised_sql(sql),
        }
    return shape


METRICS = "SELECT run_id, suite, name, variant, value FROM metrics ORDER BY 1, 2, 3, 4"
RECORDS = "SELECT id, run_id, suite, kind, payload_json FROM records ORDER BY id"
UNTOUCHED = ("runs", "suite_results", "stage_timings")


def test_the_fixture_is_a_real_version_0_store(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    _, raw = _legacy_store(path)
    assert _user_version(path) == 0
    assert len(_rows(path, METRICS)) == sum(len(s["metrics"]) for s in raw["suites"]) == 50
    assert any(row[4] == 0.0 for row in _rows(path, METRICS)), "needs a true zero to protect"
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        _write(path, "INSERT INTO metrics VALUES ('r', 's', 'm', '', NULL)")


def test_a_fresh_store_is_created_at_the_latest_version(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    ResultStore(path)
    assert STORE_SCHEMA_VERSION >= 1
    assert _user_version(path) == STORE_SCHEMA_VERSION


def test_a_legacy_store_is_upgraded_in_place_on_open(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    run_id, raw = _legacy_store(path)
    metrics_before = _rows(path, METRICS)
    records_before = _rows(path, RECORDS)
    untouched_before = {t: _rows(path, f"SELECT * FROM {t} ORDER BY 1, 2") for t in UNTOUCHED}

    store = ResultStore(path)

    assert _user_version(path) == STORE_SCHEMA_VERSION
    # Every metric row survives with its value, now stated as measured.
    metrics_after = _rows(
        path,
        "SELECT run_id, suite, name, variant, value, state, reason FROM metrics "
        "ORDER BY 1, 2, 3, 4",
    )
    assert metrics_after == [(*row, "measured", None) for row in metrics_before]
    # Every record survives byte for byte; its payload schema was never recorded.
    records_after = _rows(
        path,
        "SELECT id, run_id, suite, kind, payload_json, payload_schema FROM records ORDER BY id",
    )
    assert records_after == [(*row, None) for row in records_before]
    for table, rows in untouched_before.items():
        assert _rows(path, f"SELECT * FROM {table} ORDER BY 1, 2") == rows

    # The typed read side returns what the run recorded, each one measured.
    results = store.get_results(run_id)
    on_disk = {
        (m["suite"], m["name"], m["variant"]): m["value"]
        for s in raw["suites"]
        for m in s["metrics"]
    }
    assert {(m.suite, m.name, m.variant): m.value for m in results.metrics} == on_disk
    assert all(m.state == "measured" and m.reason is None for m in results.metrics)
    records = store.get_records(run_id, limit=1000)
    assert len(records) == 190
    assert all(r.payload_schema is None for r in records)

    ResultStore(path)  # opening a current store again changes nothing
    assert _user_version(path) == STORE_SCHEMA_VERSION
    assert len(_rows(path, METRICS)) == len(metrics_before)


def test_a_migrated_store_accepts_a_not_measured_metric(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    _legacy_store(path)
    store = ResultStore(path)
    spec = _spec(tmp_path)
    run_id = store.submit_run(spec)
    unsupported = Metric(
        suite="retrieval",
        name="recall@5",
        value=None,
        state="unsupported",
        reason="no item in qa.jsonl carries gold labels",
    )
    store.save_result(
        run_id,
        EvalRunResult(
            name=spec.name,
            spec_hash=spec.spec_hash(),
            seed=spec.seed,
            started_at="2026-10-18T00:00:00+00:00",
            finished_at="2026-10-18T00:00:01+00:00",
            suites=(SuiteResult(suite="retrieval", metrics=(unsupported,), records=()),),
            stage_stats=(),
            spec=spec,
        ),
    )
    assert store.get_results(run_id).metrics == [unsupported]


def test_a_writer_that_predates_states_still_writes_measured_rows(tmp_path: Path) -> None:
    """A worker still running the old code keeps working against a migrated
    store: its INSERT names no state, and the column default says measured."""
    path = tmp_path / "crucible.db"
    run_id, _ = _legacy_store(path)
    store = ResultStore(path)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(LEGACY_METRIC_INSERT, (run_id, "retrieval", "late", "", 0.0))
    conn.close()
    (late,) = [m for m in store.get_results(run_id).metrics if m.name == "late"]
    assert late == Metric(suite="retrieval", name="late", value=0.0)


def test_a_migrated_store_has_the_shape_of_a_fresh_one(tmp_path: Path) -> None:
    """``_SCHEMA`` and the end of ``_MIGRATIONS`` describe one shape. If they
    drift, an upgraded store and a new one quietly differ."""
    fresh, migrated = tmp_path / "fresh.db", tmp_path / "migrated.db"
    ResultStore(fresh)
    _legacy_store(migrated)
    ResultStore(migrated)
    assert _shape(migrated) == _shape(fresh)


@pytest.mark.parametrize("origin", ["fresh", "migrated"])
def test_the_store_refuses_a_value_that_contradicts_its_state(tmp_path: Path, origin: str) -> None:
    """The NOT NULL on value used to keep a NULL out of the table. The CHECK
    that replaces it keeps one out of a measured row, and keeps a number out
    of a row that was not measured."""
    path = tmp_path / "crucible.db"
    if origin == "migrated":
        _legacy_store(path)
    ResultStore(path)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _write(path, "INSERT INTO metrics VALUES ('r', 's', 'a', '', NULL, 'measured', NULL)")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _write(path, "INSERT INTO metrics VALUES ('r', 's', 'b', '', 0.0, 'unsupported', 'why')")


# Rows SQLite would otherwise accept and this build could not read back.
UNREADABLE_ROWS = {
    "no reason": "(NULL, 'unsupported', NULL)",
    "blank reason": "(NULL, 'unsupported', ' \t\n')",
    "unknown state": "(NULL, 'bogus', 'why')",
    "infinite value": "(9e999, 'measured', NULL)",
    "negative infinity": "(-9e999, 'measured', NULL)",
}


@pytest.mark.parametrize("origin", ["fresh", "migrated"])
@pytest.mark.parametrize("row", UNREADABLE_ROWS.values(), ids=UNREADABLE_ROWS.keys())
def test_the_store_refuses_a_row_metric_could_not_load(
    tmp_path: Path, origin: str, row: str
) -> None:
    """The CHECKs are Metric's own rules, so SQL never admits a row whose run
    then fails to load."""
    path = tmp_path / "crucible.db"
    if origin == "migrated":
        _legacy_store(path)
    ResultStore(path)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _write(
            path,
            f"INSERT INTO metrics (run_id, suite, name, variant, value, state, reason) "
            f"VALUES ('r', 's', 'x', '', {row[1:-1]})",
        )


def test_the_store_accepts_every_metric_state(tmp_path: Path) -> None:
    """The state CHECK lists exactly MetricState. A new state changes the DDL,
    which the shape test then holds to a new migration."""
    path = tmp_path / "crucible.db"
    ResultStore(path)
    for i, state in enumerate(get_args(MetricState)):
        value, reason = ("0.5", "NULL") if state == "measured" else ("NULL", "'why'")
        _write(
            path, f"INSERT INTO metrics VALUES ('r', 's', 'm{i}', '', {value}, '{state}', {reason})"
        )


def test_a_failed_migration_leaves_the_store_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction: a step that fails after the rebuild undoes the rebuild,
    the new column and the version stamp along with it."""
    path = tmp_path / "crucible.db"
    _legacy_store(path)
    shape_before, metrics_before = _shape(path), _rows(path, METRICS)
    steps = store_module._MIGRATIONS
    failing_last = (*steps[:-1], (*steps[-1], "SELECT * FROM no_such_table"))
    monkeypatch.setattr(store_module, "_MIGRATIONS", failing_last)

    with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
        ResultStore(path)

    assert _user_version(path) == 0
    assert _shape(path) == shape_before  # value still NOT NULL; no metrics_v1, no payload_schema
    assert _rows(path, METRICS) == metrics_before


def test_a_store_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    ResultStore(path)
    _write(path, f"PRAGMA user_version = {STORE_SCHEMA_VERSION + 1}")
    with pytest.raises(StoreSchemaError, match="newer version"):
        ResultStore(path)
    assert _user_version(path) == STORE_SCHEMA_VERSION + 1


def test_concurrent_opens_of_a_legacy_store_migrate_it_once(tmp_path: Path) -> None:
    """An API and a worker starting together against an old store. A second
    run of step 1 would fail on the column it adds, so every open succeeding
    is the evidence that it ran once."""
    path = tmp_path / "crucible.db"
    _legacy_store(path)
    metrics_before = _rows(path, METRICS)
    with ThreadPoolExecutor(max_workers=6) as pool:
        stores = list(pool.map(lambda _: ResultStore(path), range(6)))
    assert len(stores) == 6
    assert _user_version(path) == STORE_SCHEMA_VERSION
    assert _rows(path, METRICS) == metrics_before


def test_a_legacy_store_with_an_infinite_value_is_refused_unchanged(tmp_path: Path) -> None:
    """The old Metric took inf and today's refuses it. Upgrading would produce a
    run that cannot be read back, so the open stops first and names the row."""
    path = tmp_path / "crucible.db"
    run_id, _ = _legacy_store(path)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(LEGACY_METRIC_INSERT, (run_id, "security", "boom", "defense=none", 9e999))
    conn.close()
    shape_before, metrics_before = _shape(path), _rows(path, METRICS)

    with pytest.raises(StoreSchemaError, match=f"run {run_id} security/boom"):
        ResultStore(path)

    assert _user_version(path) == 0
    assert _shape(path) == shape_before
    assert _rows(path, METRICS) == metrics_before


def test_an_unknown_negative_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    ResultStore(path)
    _write(path, "PRAGMA user_version = -1")
    with pytest.raises(StoreSchemaError, match="unknown store schema -1"):
        ResultStore(path)


def test_a_file_that_is_not_a_complete_store_is_refused_untouched(tmp_path: Path) -> None:
    path = tmp_path / "notes.db"
    _write(path, "CREATE TABLE notes (body TEXT)")
    with pytest.raises(StoreSchemaError, match="missing tables: metrics, records, runs"):
        ResultStore(path)
    assert _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'") == [("notes",)]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_a_legacy_store_that_is_not_writable_says_why(tmp_path: Path) -> None:
    path = tmp_path / "crucible.db"
    _legacy_store(path)
    path.chmod(stat.S_IRUSR)
    try:
        with pytest.raises(StoreSchemaError, match="not writable"):
            ResultStore(path)
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert _user_version(path) == 0


def test_an_upgrade_that_cannot_get_the_lock_says_to_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process mid-upgrade: past the wait, the loser is told to retry
    instead of failing on a raw lock error."""
    path = tmp_path / "crucible.db"
    _legacy_store(path)
    monkeypatch.setattr(store_module, "_MIGRATION_WAIT_S", 0.2)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StoreSchemaError, match="another process is upgrading"):
            ResultStore(path)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert _user_version(path) == 0
