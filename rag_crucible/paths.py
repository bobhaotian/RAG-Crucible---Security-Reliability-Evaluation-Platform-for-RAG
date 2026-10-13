"""Filesystem conventions for run artifacts, env-overridable for containers.

RAG_CRUCIBLE_ARTIFACTS_DIR — root for indexes and the default DB (default: ./artifacts)
RAG_CRUCIBLE_DB            — result-store path (default: <artifacts>/rag-crucible.db)
RAG_CRUCIBLE_RESULTS_DIR   — root for shareable reports (default: ./results)
"""

from __future__ import annotations

import os
from pathlib import Path


def artifacts_dir() -> Path:
    return Path(os.environ.get("RAG_CRUCIBLE_ARTIFACTS_DIR", "artifacts"))


def index_dir_for(spec_name: str) -> Path:
    return artifacts_dir() / "indexes" / spec_name


def default_db_path() -> Path:
    env = os.environ.get("RAG_CRUCIBLE_DB")
    return Path(env) if env else artifacts_dir() / "rag-crucible.db"


def results_dir() -> Path:
    return Path(os.environ.get("RAG_CRUCIBLE_RESULTS_DIR", "results"))


def submitted_run_results_dir(spec_name: str, run_id: str) -> Path:
    """Collision-free report directory for one worker-executed run.

    A spec can be submitted repeatedly with ``--force``. Keeping the run id in
    the path preserves every report instead of letting the newest run overwrite
    the previous one.
    """
    return results_dir() / spec_name / run_id
