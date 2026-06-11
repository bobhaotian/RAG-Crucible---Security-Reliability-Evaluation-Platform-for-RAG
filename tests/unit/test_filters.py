"""Filter chain behavior: dedup, language gate, boilerplate stripping."""

from __future__ import annotations

from crucible.ingest import apply_filters
from crucible.types import DocMeta, Document, doc_id_for

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
