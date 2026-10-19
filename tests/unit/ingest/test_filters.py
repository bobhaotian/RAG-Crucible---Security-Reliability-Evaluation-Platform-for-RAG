"""Filter chain behavior: dedup, language gate, boilerplate stripping."""

from __future__ import annotations

import pytest

from rag_crucible.ingest import apply_filters, apply_filters_after
from rag_crucible.types import DocMeta, Document, doc_id_for

ENGLISH = (
    "The quarterly report shows that the team shipped all of the planned features "
    "and the customers were satisfied with the results of the release."
)
FRENCH = (
    "Le rapport trimestriel montre que l'équipe a livré toutes les fonctionnalités "
    "prévues et que les clients étaient satisfaits des résultats de la version."
)


def _doc(source: str, text: str) -> Document:
    return Document(
        doc_id=doc_id_for(source, text), source=source, text=text, meta=DocMeta(filetype="txt")
    )


def test_dedup_keeps_first_occurrence() -> None:
    docs = [
        _doc("a/original.txt", ENGLISH),
        _doc("z/copy.txt", ENGLISH),
        _doc("b/other.txt", ENGLISH + " Extra sentence to differ."),
    ]
    kept, stats = apply_filters(docs, ["dedup"])
    assert [d.source for d in kept] == ["a/original.txt", "b/other.txt"]
    assert stats[0].dropped == 1
    assert stats[0].dropped_documents[0].source == "z/copy.txt"
    assert stats[0].dropped_documents[0].reason == "duplicate_content"


def test_language_filter_drops_non_english() -> None:
    docs = [_doc("en.txt", ENGLISH), _doc("fr.txt", FRENCH)]
    kept, stats = apply_filters(docs, ["language"])
    assert [d.source for d in kept] == ["en.txt"]
    assert stats[0].dropped == 1


def test_language_filter_passes_short_docs() -> None:
    docs = [_doc("short.txt", "AT-300 spec sheet")]
    kept, _ = apply_filters(docs, ["language"])
    assert len(kept) == 1


def test_boilerplate_strips_lines_but_never_reflows() -> None:
    text = (
        f"{ENGLISH}\n"
        "Copyright 2026 Helios Robotics.\n"
        "All rights reserved.\n"
        f"{ENGLISH} Second paragraph keeps its exact line.\n"
    )
    docs = [_doc("page.txt", text)]
    kept, stats = apply_filters(docs, ["boilerplate"])
    assert stats[0].dropped == 0
    assert "Copyright" not in kept[0].text
    # surviving lines are intact, so substring gold labels stay valid
    assert f"{ENGLISH} Second paragraph keeps its exact line." in kept[0].text


def test_boilerplate_drops_docs_with_no_content_left() -> None:
    text = "Copyright 2026.\nAll rights reserved.\nSubscribe to our newsletter today.\n"
    kept, stats = apply_filters([_doc("junk.txt", text)], ["boilerplate"])
    assert kept == []
    assert stats[0].dropped == 1


def test_filters_run_in_order_and_report_per_filter() -> None:
    docs = [_doc("en.txt", ENGLISH), _doc("fr.txt", FRENCH), _doc("fr2.txt", FRENCH)]
    kept, stats = apply_filters(docs, ["dedup", "language", "boilerplate"])
    assert [s.name for s in stats] == ["dedup", "language", "boilerplate"]
    assert [s.dropped for s in stats] == [1, 1, 0]
    assert [d.source for d in kept] == ["en.txt"]


def test_a_second_batch_loses_a_duplicate_to_the_corpus_whatever_its_path() -> None:
    corpus = [_doc("z/original.txt", ENGLISH), _doc("z/other.txt", FRENCH)]
    # Sorts ahead of the corpus copy: ordering by path would keep it instead.
    batch = [_doc("a/planted.md", ENGLISH), _doc("m/fresh.md", ENGLISH + " Unique.")]
    kept, stats = apply_filters_after(corpus, batch, ["dedup", "language"])
    assert [d.source for d in kept] == ["m/fresh.md"]
    # Only the batch's drops are reported; the corpus's French file is not.
    assert [(s.name, s.dropped) for s in stats] == [("dedup", 1), ("language", 0)]
    assert stats[0].dropped_documents[0].source == "a/planted.md"
    assert stats[0].dropped_documents[0].reason == "duplicate_content"


def test_a_second_batch_meets_each_filter_as_a_corpus_file_would() -> None:
    secret = "canary07-1f2e@example-corp.test"
    batch = [
        _doc("kb/fr.md", FRENCH),
        _doc("kb/entry.md", f"{ENGLISH} Reach the lead at {secret}."),
    ]
    kept, stats = apply_filters_after([_doc("kb/en.md", ENGLISH)], batch, ["language", "pii"])
    assert [d.source for d in kept] == ["kb/entry.md"]
    assert stats[0].dropped_documents[0].reason == "language_not_supported"
    assert secret not in kept[0].text  # rewritten in place, as `pii` does to the corpus
    assert kept[0].doc_id == batch[1].doc_id  # identity survives the rewrite


def test_a_second_batch_leaves_the_corpus_outcome_alone() -> None:
    corpus = [_doc("a.txt", ENGLISH), _doc("b.txt", ENGLISH), _doc("c.txt", FRENCH)]
    names = ["dedup", "language", "boilerplate"]
    alone, _ = apply_filters(corpus, names)
    together, _ = apply_filters([*corpus, _doc("z.md", ENGLISH + " New.")], names)
    assert together[: len(alone)] == alone


def test_a_second_batch_cannot_reuse_a_corpus_doc_id() -> None:
    doc = _doc("kb/a.md", ENGLISH)
    with pytest.raises(ValueError, match="shares a doc_id"):
        apply_filters_after([doc], [doc], ["dedup"])
