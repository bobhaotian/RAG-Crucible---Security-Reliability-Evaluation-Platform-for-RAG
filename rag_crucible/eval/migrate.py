"""Read result artifacts written by older versions of this tool.

Writes are always current and strictly validated. Reads go through
``load_result_json``, which walks a raw artifact up the migration chain one
version at a time and only then validates it. Two rules govern every step:

1. **Never invent a value.** A field an older writer did not record becomes
   ``None`` — *unavailable* — not ``0``, ``""``, ``()`` or ``False``. The
   difference matters: an empty marker tuple says the answer was scanned and
   nothing was found; ``None`` says the run never scanned. A migration that
   defaults the second into the first manufactures a measurement, which is the
   failure this whole module exists to prevent.
2. **Drop only what is now derived.** A key that became a computed property is
   removed, because the property recomputes it from the fields it derives from.
   A key whose meaning changed is *not* silently reinterpreted — that needs a
   new version and an explicit step here.

Refusing to read is a valid outcome. An artifact from a future version, or one
whose version is unrecognisable, raises rather than being coerced into the
current shape.

**Migration is read-only. Do not write a migrated artifact back over the
original.** The embedded ``spec`` is not version-stable: re-serialising a
historical result through today's ``RunSpec`` fills in options that did not
exist when it ran (``answer_integrity``, ``disjoint_targets``,
``clean_control_sample`` were all added later), which both backdates settings
into a run that never had them and breaks the stored ``spec_hash`` — the file
would then assert a hash its own embedded spec does not produce. Upgrading a
stored artifact therefore means re-running the spec under a new run id, not
rewriting the old file. ``test_stored_spec_hash_matches_the_stored_spec``
guards the property this relies on.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag_crucible.eval.types import RESULT_SCHEMA_VERSION, EvalRunResult

# Everything written before versioning existed carries no schema_version key.
_UNVERSIONED = 1


class ResultSchemaError(Exception):
    """A stored result cannot be read into the current models."""


def _migrate_1_to_2(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema 1 → 2.

    Drops exactly one key: ``foreign_markers``. It was stored as data and is
    now a property derived from ``matched_markers`` and ``own_marker``, so a
    stored list would be a second, un-recomputable source of truth.

    **Everything else is left exactly as the writer left it**, and that is the
    whole subtlety of this step. Schema 1 is not one shape — it is every
    artifact written before versioning existed, which spans writers that did
    record ``own_marker`` / ``matched_markers`` / ``abstained`` and writers
    that did not. Deleting those keys to "normalise" the shape would erase
    real measurements from the artifacts that have them: the committed
    ``results/smoke-fake`` run records all 36 marker scans, 31 of them
    non-empty. So presence is preserved and absence is left to the model's
    ``None`` default, which is what makes absence read as *unavailable*.

    The rule this encodes cuts both ways. Never invent a value the writer did
    not record — and never destroy one it did.
    """
    for suite in raw.get("suites") or []:
        for record in suite.get("records") or []:
            if record.get("kind") == "attack":
                record.pop("foreign_markers", None)
    raw.setdefault("run_id", None)  # unavailable unless the writer recorded one
    return raw


def _migrate_2_to_3(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema 2 → 3: old writers did not preserve ingestion evidence."""
    raw.setdefault("ingestion", None)
    return raw


def _migrate_3_to_4(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema 3 → 4: older writers did not pin corpus content digests."""
    spec = raw.get("spec")
    if isinstance(spec, dict):
        identity = json.dumps(spec, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(identity.encode()).hexdigest() == raw.get("spec_hash"):
            raw.setdefault("spec_identity_json", identity)
    corpus = (raw.get("spec") or {}).get("corpus")
    if isinstance(corpus, dict):
        corpus.setdefault("documents_digest", None)
        corpus.setdefault("qa_digest", None)
    return raw


def _migrate_4_to_5(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema 4 → 5: old runs contain no clean-chunk screening trials."""
    return raw


# version -> migration producing version+1. Every consecutive step from
# _UNVERSIONED to RESULT_SCHEMA_VERSION must be present.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
    3: _migrate_3_to_4,
    4: _migrate_4_to_5,
}


def supported_versions() -> tuple[int, ...]:
    return tuple(range(_UNVERSIONED, RESULT_SCHEMA_VERSION + 1))


def migrate_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Walk a decoded artifact up to the current schema version."""
    version = raw.get("schema_version", _UNVERSIONED)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ResultSchemaError(f"schema_version must be an integer, got {version!r}")
    if version > RESULT_SCHEMA_VERSION:
        raise ResultSchemaError(
            f"result was written by a newer version (schema {version}; this build "
            f"reads up to {RESULT_SCHEMA_VERSION}). Upgrade rag-crucible to read it."
        )
    if version < _UNVERSIONED:
        raise ResultSchemaError(f"unknown result schema version {version}")

    while version < RESULT_SCHEMA_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:  # pragma: no cover - guarded by test_migration_chain_is_complete
            raise ResultSchemaError(f"no migration registered from schema {version}")
        raw = migration(raw)
        version += 1
    raw["schema_version"] = RESULT_SCHEMA_VERSION
    return raw


def load_result_json(text: str) -> EvalRunResult:
    """Parse a stored results.json of any supported version, strictly."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResultSchemaError(f"result is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ResultSchemaError(f"result must be a JSON object, got {type(raw).__name__}")
    return EvalRunResult.model_validate(migrate_raw(raw))


def load_result_file(path: Path) -> EvalRunResult:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResultSchemaError(f"cannot read {path}: {exc}") from exc
    try:
        return load_result_json(text)
    except ResultSchemaError as exc:
        raise ResultSchemaError(f"{path}: {exc}") from exc
