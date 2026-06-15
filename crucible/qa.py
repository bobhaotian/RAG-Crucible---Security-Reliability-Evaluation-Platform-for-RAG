"""Labeled QA datasets and gold-relevance judgments.

Two gold-label kinds, one schema (``qa.jsonl``, one object per line):

- fact-substring (the seeded corpus): ``gold_fact`` is a sentence appearing
  verbatim in one document; a chunk is relevant iff it contains the fact.
  This makes labels independent of the chunking configuration.
- document ids (BEIR-style qrels, e.g. SciFact): ``gold_docs`` lists corpus
  sources; a chunk is relevant iff it comes from one of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import model_validator

from crucible.types import Chunk, StrictModel


class QAItem(StrictModel):
    qid: str
    question: str
    answer: str | None = None
    gold_doc: str | None = None  # informational; relevance uses gold_fact
    gold_fact: str | None = None
    gold_docs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _has_gold(self) -> QAItem:
        if self.gold_fact is None and not self.gold_docs:
            raise ValueError(f"QA item {self.qid} needs gold_fact or gold_docs")
        return self


class QADatasetError(Exception):
    pass


def load_qa(path: Path) -> list[QAItem]:
    if not path.is_file():
        raise QADatasetError(f"QA file not found: {path}")
    items: list[QAItem] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(QAItem.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise QADatasetError(f"{path}:{line_number}: {exc}") from exc
    if not items:
        raise QADatasetError(f"QA file is empty: {path}")
    return items


_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def is_relevant(chunk: Chunk, item: QAItem) -> bool:
    if item.gold_fact is not None:
        return _normalize(item.gold_fact) in _normalize(chunk.text)
    return chunk.source in item.gold_docs


def answer_matches(answer_text: str, item: QAItem) -> bool:
    """Cheap deterministic answer check: the gold answer string appears in the
    generated answer (whitespace/case-insensitive, digit grouping ignored)."""
    if item.answer is None:
        return False
    return _normalize(item.answer).replace(",", "") in _normalize(answer_text).replace(",", "")
