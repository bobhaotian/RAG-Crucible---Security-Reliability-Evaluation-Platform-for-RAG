"""Filesystem conventions for run artifacts, env-overridable for containers.

CRUCIBLE_ARTIFACTS_DIR — root for indexes and the default DB (default: ./artifacts)
CRUCIBLE_DB            — result-store path (default: <artifacts>/crucible.db)
"""

from __future__ import annotations

import os
from pathlib import Path


def artifacts_dir() -> Path:
    return Path(os.environ.get("CRUCIBLE_ARTIFACTS_DIR", "artifacts"))


def index_dir_for(spec_name: str) -> Path:
    return artifacts_dir() / "indexes" / spec_name


def default_db_path() -> Path:
    env = os.environ.get("CRUCIBLE_DB")
    return Path(env) if env else artifacts_dir() / "crucible.db"
