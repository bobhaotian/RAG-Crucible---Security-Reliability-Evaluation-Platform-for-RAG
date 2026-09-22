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
        corpus = raw.get("corpus")
        if isinstance(corpus, dict):
            corpus = dict(corpus)
            for key in ("documents", "qa"):
                value = corpus.get(key)
                if value is not None and not Path(value).is_absolute():
                    corpus[key] = (path.parent / value).resolve()
            raw = dict(raw)
            raw["corpus"] = corpus
        suites = raw.get("suites")
        if isinstance(suites, dict):
            faithfulness = suites.get("faithfulness")
            if isinstance(faithfulness, dict):
                judge = faithfulness.get("judge")
                if isinstance(judge, dict) and judge.get("cache") is not None:
                    judge = dict(judge)
                    cache = Path(judge["cache"])
                    if not cache.is_absolute():
                        judge["cache"] = (path.parent / cache).resolve()
                    faithfulness = dict(faithfulness)
                    faithfulness["judge"] = judge
                    suites = dict(suites)
                    suites["faithfulness"] = faithfulness
                    raw["suites"] = suites
        return RunSpec.model_validate(raw).with_content_digests()
    except (ValidationError, ValueError) as exc:
        raise SpecError(f"invalid spec {path}:\n{exc}") from exc
