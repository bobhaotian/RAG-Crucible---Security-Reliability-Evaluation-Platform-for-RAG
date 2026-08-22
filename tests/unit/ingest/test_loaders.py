"""Loader behavior per file type, plus corpus-level determinism."""

from __future__ import annotations

from pathlib import Path

import pytest
from fpdf import FPDF

from crucible.ingest import LoaderError, load_corpus


def _write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def mixed_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    _write(root, "note.md", "# A Title\n\nThe fact sentence lives here.\n")
    _write(root, "plain.txt", "Plain text content for loading.\n")
    _write(
        root,
        "page.html",
        "<html><head><title>Page Title</title></head><body>"
        "<h1>Heading One</h1><h2>Sub Heading</h2>"
        "<p>The HTML fact sentence is preserved on one line.</p>"
        "<script>ignored()</script></body></html>",
    )
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "PDF body text for the loader.", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(root / "doc.pdf"))
    _write(root, "ignored.xyz", "unsupported")
    return root


def test_load_corpus_loads_each_type_and_skips_unknown(mixed_corpus: Path) -> None:
    docs, skipped = load_corpus(mixed_corpus)
    by_source = {d.source: d for d in docs}
    assert set(by_source) == {"note.md", "plain.txt", "page.html", "doc.pdf"}
    assert skipped == ["ignored.xyz"]

    assert by_source["note.md"].meta.title == "A Title"
    assert "The fact sentence lives here." in by_source["note.md"].text

    html = by_source["page.html"]
    assert html.meta.title == "Page Title"
    assert "# Heading One" in html.text  # headings become markdown for the structure chunker
    assert "## Sub Heading" in html.text
    assert "The HTML fact sentence is preserved on one line." in html.text
    assert "ignored()" not in html.text

    assert "PDF body text" in by_source["doc.pdf"].text


def test_doc_ids_are_stable_across_loads(mixed_corpus: Path) -> None:
    first, _ = load_corpus(mixed_corpus)
    second, _ = load_corpus(mixed_corpus)
    assert [d.doc_id for d in first] == [d.doc_id for d in second]
    assert [d.source for d in first] == sorted(d.source for d in first)


def test_missing_corpus_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(LoaderError, match="not found"):
        load_corpus(tmp_path / "absent")
