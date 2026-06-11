"""Document loaders: one per file type, registered by suffix.

The registry is the pluggable seam — a crawler or any new source registers a
loader function and the rest of the pipeline is unchanged. Loaders normalize
to plain text but preserve structure cues: HTML headings become markdown-style
``#`` prefixes so the structure-aware chunker works across formats.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

from crucible.types import DocMeta, Document, doc_id_for


class LoaderError(Exception):
    """A file matched a registered suffix but could not be loaded."""


LoaderFn = Callable[[Path, str], Document]

_LOADERS: dict[str, LoaderFn] = {}


def register_loader(suffix: str, fn: LoaderFn) -> None:
    _LOADERS[suffix.lower()] = fn


def supported_suffixes() -> tuple[str, ...]:
    return tuple(sorted(_LOADERS))


def load_corpus(root: Path) -> tuple[list[Document], list[str]]:
    """Load every supported file under ``root`` (sorted for determinism).

    Returns (documents, skipped) where skipped lists relative paths whose
    suffix has no registered loader.
    """
    if not root.is_dir():
        raise LoaderError(f"corpus directory not found: {root}")
    documents: list[Document] = []
    skipped: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        source = path.relative_to(root).as_posix()
        loader = _LOADERS.get(path.suffix.lower())
        if loader is None:
            skipped.append(source)
            continue
        try:
            documents.append(loader(path, source))
        except Exception as exc:
            raise LoaderError(f"failed to load {source}: {exc}") from exc
    return documents, skipped


def _make_document(source: str, text: str, filetype: str, title: str | None) -> Document:
    return Document(
        doc_id=doc_id_for(source, text),
        source=source,
        text=text,
        meta=DocMeta(title=title, filetype=filetype),
    )


def _load_text(path: Path, source: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    return _make_document(source, text, path.suffix.lstrip(".").lower(), title=path.stem)


def _load_markdown(path: Path, source: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = next(
        (line[2:].strip() for line in text.splitlines() if line.startswith("# ")),
        path.stem,
    )
    return _make_document(source, text, "md", title=title)


_HTML_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote")


def _load_html(path: Path, source: str) -> Document:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines: list[str] = []
    for el in soup.find_all(_HTML_BLOCK_TAGS):
        content = el.get_text(" ", strip=True)
        if not content:
            continue
        if el.name and el.name.startswith("h") and el.name[1:].isdigit():
            lines.append(f"{'#' * int(el.name[1:])} {content}")
        else:
            lines.append(content)
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else path.stem
    return _make_document(source, "\n\n".join(lines), "html", title=title)


def _load_pdf(path: Path, source: str) -> Document:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return _make_document(source, "\n\n".join(pages).strip(), "pdf", title=path.stem)


register_loader(".txt", _load_text)
register_loader(".md", _load_markdown)
register_loader(".html", _load_html)
register_loader(".htm", _load_html)
register_loader(".pdf", _load_pdf)
