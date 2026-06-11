"""QA dataset loading, both gold-label kinds, and answer matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.eval.qa import QADatasetError, QAItem, answer_matches, is_relevant, load_qa
from crucible.types import Chunk, chunk_id_for

REPO_ROOT = Path(__file__).resolve().parents[2]


def _chunk(text: str, source: str = "doc.md") -> Chunk:
    return Chunk(
        chunk_id=chunk_id_for("d000000000000000", 0, len(text)),
        doc_id="d000000000000000",
        source=source,
        text=text,
        start=0,
        end=len(text),
    )


def test_seeded_qa_loads() -> None:
    items = load_qa(REPO_ROOT / "datasets" / "seeded" / "qa.jsonl")
    assert len(items) == 56
    assert all(item.gold_fact is not None for item in items)


def test_fact_substring_relevance_normalizes_whitespace() -> None:
    item = QAItem(qid="q1", question="?", gold_fact="The X1 has a battery life of 72 hours.")
    wrapped = _chunk("intro text\nThe X1 has a battery life\nof 72 hours. trailing")
    unrelated = _chunk("totally different content")
    assert is_relevant(wrapped, item)
    assert not is_relevant(unrelated, item)


def test_doc_ids_relevance_matches_source() -> None:
    item = QAItem(qid="q2", question="?", gold_docs=("123.txt", "456.txt"))
    assert is_relevant(_chunk("anything", source="456.txt"), item)
    assert not is_relevant(_chunk("anything", source="789.txt"), item)


def test_gold_label_required() -> None:
    with pytest.raises(ValueError, match="gold_fact or gold_docs"):
        QAItem(qid="q3", question="?")


def test_answer_matches_ignores_case_whitespace_and_digit_grouping() -> None:
    item = QAItem(qid="q4", question="?", answer="41,000 USD", gold_fact="x")
    assert answer_matches("It is priced at 41,000  usd.", item)
    assert answer_matches("The price is 41000 USD today.", item)
    assert not answer_matches("It costs 42,000 USD.", item)
    assert not answer_matches("anything", QAItem(qid="q5", question="?", gold_fact="x"))


def test_load_qa_errors_are_actionable(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    with pytest.raises(QADatasetError, match="not found"):
        load_qa(missing)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"qid": "q1"}\n', encoding="utf-8")
    with pytest.raises(QADatasetError, match=r"bad\.jsonl:1"):
        load_qa(bad)
