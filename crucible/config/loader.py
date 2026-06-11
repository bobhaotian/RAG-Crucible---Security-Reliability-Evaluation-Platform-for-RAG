"""YAML → RunSpec with errors that name the file and the offending field."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from crucible.config.models import RunSpec


class SpecError(Exception):
    """A spec file is missing, unreadable, or fails validation."""


def load_spec(path: Path) -> RunSpec:
    if not path.is_file():
        raise SpecError(f"spec file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise SpecError(f"{path} must contain a YAML mapping at the top level")
    try:
        return RunSpec.model_validate(raw)
    except ValidationError as exc:
        raise SpecError(f"invalid spec {path}:\n{exc}") from exc
