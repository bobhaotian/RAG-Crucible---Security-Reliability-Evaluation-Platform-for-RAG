"""Reading result artifacts written by older versions.

The rule under test throughout: a field an older writer did not record reads
as *unavailable*, never as a value. A migration that turns "never scanned"
into "scanned, found nothing" manufactures a measurement.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crucible.eval.migrate import (
    ResultSchemaError,
    load_result_file,
    load_result_json,
    migrate_raw,
    supported_versions,
)
from crucible.eval.types import RESULT_SCHEMA_VERSION, AttackRecord, EvalRunResult, SuiteResult
from crucible.runner.models import SuiteSummary

# Anchored to the file, not the working directory: a CWD-relative glob that
# finds nothing turns the artifact test below into a vacuous pass.
REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_ARTIFACTS = sorted((REPO_ROOT / "results").rglob("results.json"))


def _spec_json() -> dict[str, Any]:
    """A minimal valid spec, taken from a committed artifact so it stays real."""
    committed = REPO_ROOT / "results/smoke-fake/results.json"
    return json.loads(committed.read_text(encoding="utf-8"))["spec"]


def _schema_1_artifact() -> dict[str, Any]:
    """A schema-1 result shaped like the oldest real one in the repo.

    Modelled on the committed `results/demo` run: no `schema_version`, no
    `run_id`, and attack records that stored `foreign_markers` while recording
    neither the marker scan nor `compromised`.
    """
    return {
        "name": "legacy-run",
        "spec_hash": "a" * 64,
        "seed": 42,
        "started_at": "2026-06-01T00:00:00+00:00",
        "finished_at": "2026-06-01T00:01:00+00:00",
        "stage_stats": [],
        "spec": _spec_json(),
        "suites": [
            {
                "suite": "security",
                "status": "succeeded",
                "error": None,
                "metrics": [],
                "records": [
                    {
                        "kind": "attack",
                        "attack_type": "poison",
                        "qid": "q1",
                        "question": "q?",
                        "defense": "none",
                        "retrieved": True,
                        "succeeded": False,
                        "foreign_markers": [],
                        "answer": "14 hours",
                    }
                ],
            }
        ],
    }


def test_schema_1_artifact_loads() -> None:
    result = load_result_json(json.dumps(_schema_1_artifact()))
    assert result.schema_version == RESULT_SCHEMA_VERSION
    assert result.name == "legacy-run"


def test_fields_schema_1_never_recorded_read_as_unavailable() -> None:
    """The core rule. Not False, not "", not () — None."""
    result = load_result_json(json.dumps(_schema_1_artifact()))
    record = result.suites[0].records[0]
    assert isinstance(record, AttackRecord)

    assert result.run_id is None, "an id the writer never assigned is not a value"
    assert record.abstained is None, "unrecorded refusal must not read as 'did not refuse'"
    assert record.matched_markers is None, "an unscanned answer is not an empty scan"
    assert record.own_marker is None
    assert record.compromised is None, "an unscanned trial is not an uncompromised one"


def test_derived_markers_are_unavailable_not_empty_for_schema_1() -> None:
    """The consequence that matters: a run that never measured cross-attack
    contamination must not report zero of it."""
    result = load_result_json(json.dumps(_schema_1_artifact()))
    record = result.suites[0].records[0]
    assert isinstance(record, AttackRecord)

    assert record.foreign_markers is None
    assert record.competing_markers is None
    assert record.cross_question_markers is None


def test_recorded_empty_stays_empty_and_is_distinguishable() -> None:
    """The other half: a genuine zero survives as a zero."""
    scanned = AttackRecord(
        attack_type="poison",
        qid="q1",
        question="q?",
        defense="none",
        retrieved=True,
        succeeded=False,
        own_marker="900000",
        matched_markers=(),
        abstained=False,
        answer="14 hours",
    )
    assert scanned.matched_markers == ()
    assert scanned.foreign_markers == ()  # measured, and nothing was there
    assert scanned.foreign_markers is not None


def test_schema_1_that_did_record_the_scan_keeps_every_value() -> None:
    """The other direction of the rule, and the one that is easy to get wrong.

    Schema 1 is not a single shape — it is everything written before
    versioning existed, spanning writers that recorded the marker scan and
    writers that did not. Normalising the shape by deleting those keys would
    erase real measurements. Presence must survive untouched.
    """
    raw = _schema_1_artifact()
    record = raw["suites"][0]["records"][0]
    record["own_marker"] = "900000"
    record["matched_markers"] = [{"marker": "900009", "attack_type": "poison", "qid": "q9"}]
    record["abstained"] = True

    migrated = load_result_json(json.dumps(raw)).suites[0].records[0]
    assert isinstance(migrated, AttackRecord)
    assert migrated.own_marker == "900000"
    assert migrated.abstained is True
    assert migrated.matched_markers is not None
    assert [m.marker for m in migrated.matched_markers] == ["900009"]
    # and the derived view is computable again, not unavailable
    assert migrated.cross_question_markers is not None
    assert [m.qid for m in migrated.cross_question_markers] == ["q9"]


def test_compromised_is_unavailable_when_the_scan_was_not_recorded() -> None:
    """`compromised` is the boolean view of the same scan `matched_markers`
    details, so it cannot be available when that scan is not. Defaulting it to
    False would say "not compromised" about a trial nobody scanned."""
    record = load_result_json(json.dumps(_schema_1_artifact())).suites[0].records[0]
    assert isinstance(record, AttackRecord)
    assert record.compromised is None


def test_compromise_rate_is_omitted_not_zeroed_for_unrecorded_trials() -> None:
    """The metric that would otherwise report a fabricated 0.0.

    It also must not be computed over just the subset that recorded the scan:
    its documented meaning is `compromise - success` on a shared denominator,
    which a subset silently breaks.
    """
    from crucible.config import SecuritySuiteConfig
    from crucible.eval.security import _aggregate

    def rec(**kw: Any) -> AttackRecord:
        base = {
            "attack_type": "poison",
            "qid": "q1",
            "question": "q?",
            "defense": "none",
            "retrieved": True,
            "succeeded": False,
            "answer": "",
        }
        return AttackRecord.model_validate({**base, **kw})

    config = SecuritySuiteConfig(defenses=("none",))

    unrecorded = [rec(qid="q1"), rec(qid="q2")]  # compromised defaults to None
    names = {m.name for m in _aggregate(unrecorded, config)}
    assert "knowledge_corruption_rate" in names, "success is still measurable"
    assert "poison_compromise_rate" not in names, "must not report a 0.0 nobody measured"

    # Mixed: one trial recorded the scan, one did not -> still omitted, because
    # a partial denominator breaks the pair's stated relationship.
    mixed = [rec(qid="q1", compromised=True, matched_markers=()), rec(qid="q2")]
    assert "poison_compromise_rate" not in {m.name for m in _aggregate(mixed, config)}

    # Fully recorded -> reported, on the same denominator as success.
    full = [
        rec(qid="q1", compromised=True, matched_markers=()),
        rec(qid="q2", compromised=False, matched_markers=()),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(full, config)}
    assert metrics[("poison_compromise_rate", "defense=none")] == 0.5


_PRESERVED_ATTACK_FIELDS = ("own_marker", "matched_markers", "abstained", "compromised")


def _recorded_counts(path: Path) -> dict[str, int]:
    """How many attack records on disk carry each preserved field."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = [r for s in raw["suites"] for r in s["records"] if r["kind"] == "attack"]
    return {f: sum(1 for r in records if r.get(f) is not None) for f in _PRESERVED_ATTACK_FIELDS}


@pytest.mark.parametrize("path", RESULT_ARTIFACTS, ids=lambda p: p.parent.name)
def test_migration_preserves_every_recorded_scan(path: Path) -> None:
    """No real artifact loses a value it recorded.

    Stated as a property over whatever artifacts exist rather than against one
    named file, because the file this bug was found on turned out to be an
    uncommitted local run — the earlier version of this test passed locally and
    failed in CI. `test_the_artifact_corpus_exercises_preservation` below keeps
    the property from going vacuous.
    """
    on_disk = _recorded_counts(path)
    loaded = [r for s in load_result_file(path).suites for r in s.records if r.kind == "attack"]
    for field in _PRESERVED_ATTACK_FIELDS:
        after = sum(1 for r in loaded if getattr(r, field) is not None)
        assert after == on_disk[field], (
            f"{path}: {field} recorded on {on_disk[field]} records but only {after} survived"
        )


def test_the_artifact_corpus_exercises_preservation() -> None:
    """At least one committed artifact must actually carry a recorded scan,
    or the parametrized preservation test above proves nothing."""
    total = sum(_recorded_counts(p)["matched_markers"] for p in RESULT_ARTIFACTS)
    assert total > 0, "no artifact carries a recorded marker scan; preservation is untested"


def test_stored_foreign_markers_key_is_dropped_not_reinterpreted() -> None:
    """`foreign_markers` became a derived property. The stored list cannot be
    turned back into matched_markers + own_marker, so it is discarded rather
    than guessed at."""
    raw = _schema_1_artifact()
    raw["suites"][0]["records"][0]["foreign_markers"] = [
        {"marker": "900009", "attack_type": "poison", "qid": "q9"}
    ]
    result = load_result_json(json.dumps(raw))
    record = result.suites[0].records[0]
    assert isinstance(record, AttackRecord)
    assert record.matched_markers is None
    assert record.foreign_markers is None


def test_new_writes_carry_the_current_version_and_validate_strictly() -> None:
    raw = _schema_1_artifact()
    raw["schema_version"] = RESULT_SCHEMA_VERSION
    raw["run_id"] = "01ABCDEF"
    raw["suites"][0]["records"][0].pop("foreign_markers")
    result = load_result_json(json.dumps(raw))
    assert result.run_id == "01ABCDEF"

    # An unknown key is still an error at the current version.
    raw["nonsense"] = 1
    with pytest.raises(ValidationError, match=r"Extra inputs are not permitted"):
        load_result_json(json.dumps(raw))


def test_a_future_version_is_refused_rather_than_coerced() -> None:
    raw = _schema_1_artifact()
    raw["schema_version"] = RESULT_SCHEMA_VERSION + 1
    with pytest.raises(ResultSchemaError, match="newer version"):
        load_result_json(json.dumps(raw))


@pytest.mark.parametrize("bad", ["2", 2.0, True, None, [2]])
def test_a_non_integer_version_is_refused(bad: object) -> None:
    raw = _schema_1_artifact()
    raw["schema_version"] = bad
    with pytest.raises(ResultSchemaError, match="must be an integer"):
        migrate_raw(raw)


def test_migration_chain_is_complete() -> None:
    """Every consecutive step from the oldest supported version to the current
    one must exist, so bumping the version without writing a migration fails
    here rather than on a user's artifact."""
    from crucible.eval.migrate import _MIGRATIONS, _UNVERSIONED

    for version in range(_UNVERSIONED, RESULT_SCHEMA_VERSION):
        assert version in _MIGRATIONS, f"no migration registered from schema {version}"
    assert supported_versions()[0] == _UNVERSIONED
    assert supported_versions()[-1] == RESULT_SCHEMA_VERSION


def test_malformed_input_is_reported_not_crashed(tmp_path: Path) -> None:
    with pytest.raises(ResultSchemaError, match="not valid JSON"):
        load_result_json("{not json")
    with pytest.raises(ResultSchemaError, match="must be a JSON object"):
        load_result_json("[1, 2]")
    missing = tmp_path / "nope.json"
    with pytest.raises(ResultSchemaError, match="cannot read"):
        load_result_file(missing)


# --- the second acceptance criterion: one suite status, not two -------------


def test_suite_status_cannot_diverge_between_eval_and_store() -> None:
    """`SuiteResult.status` and `SuiteSummary.status` must be the same alias.

    Spelled separately they drift, and a status the eval layer can produce
    becomes one the result store rejects — which surfaces as a 500 from the
    API rather than a type error.
    """
    from typing import get_args

    eval_side = set(get_args(SuiteResult.model_fields["status"].annotation))
    store_side = set(get_args(SuiteSummary.model_fields["status"].annotation))
    assert eval_side == store_side, f"diverged: {eval_side ^ store_side}"
    assert "skipped" in eval_side, "a skipped suite must be representable on both sides"


def test_a_skipped_suite_round_trips_through_both_models() -> None:
    suite = SuiteResult(suite="retrieval", status="skipped", metrics=(), records=())
    summary = SuiteSummary(suite=suite.suite, status=suite.status, metric_count=0, record_count=0)
    assert summary.status == "skipped"


# --- every committed artifact must remain readable --------------------------


@pytest.mark.parametrize("path", RESULT_ARTIFACTS, ids=lambda p: p.parent.name)
def test_stored_spec_hash_matches_the_stored_spec(path: Path) -> None:
    """Every artifact is internally consistent: its `spec_hash` is the hash of
    the `spec` it actually carries.

    This is the property that makes migration read-only. Re-serialising the
    embedded spec through today's `RunSpec` fills in options added since the
    run (`answer_integrity`, `disjoint_targets`, `clean_control_sample`), which
    changes the hash — so writing a migrated artifact back over the original
    would make the file contradict itself and backdate settings into a run that
    never had them. Migration upgrades results on read; upgrading one on disk
    means re-running the spec under a new run id.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(raw["spec"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(blob.encode()).hexdigest() == raw["spec_hash"], (
        f"{path} claims a spec_hash its own embedded spec does not produce"
    )


def test_there_are_result_artifacts_to_check() -> None:
    """Keeps the parametrized test below from passing on an empty list."""
    assert RESULT_ARTIFACTS, f"no results.json found under {REPO_ROOT / 'results'}"


@pytest.mark.parametrize("path", RESULT_ARTIFACTS, ids=lambda p: p.parent.name)
def test_committed_result_artifacts_load(path: Path) -> None:
    """Guards the regression that motivated this item: a shipped artifact that
    the current models can no longer parse."""
    result = load_result_file(path)
    assert result.schema_version == RESULT_SCHEMA_VERSION
    assert isinstance(result, EvalRunResult)
