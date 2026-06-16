"""Corpus filter chain: dedup, language, boilerplate, pii.

Each filter consumes and yields ``Document`` lists, so adding one never
touches its neighbors; the chain reports per-filter drop counts that the CLI
surfaces. ``pii`` is opt-in (not in the default chain) — it redacts PII in
place rather than dropping documents, and shares its redaction with the
privacy suite's defense condition.

The language filter is a deterministic stopword-ratio heuristic rather than a
language-detection dependency: real detectors are seeded-random and heavier
than this job needs — we only gate "is this English-ish prose."
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence

from crucible.config import FilterName
from crucible.ingest.pii import redact_pii
from crucible.types import Document, StrictModel


class FilterStats(StrictModel):
    name: str
    dropped: int


_WORD_RE = re.compile(r"[a-zA-Z']+")

# High-frequency English function words; English prose typically scores well
# above the threshold, other languages well below.
_EN_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "for",
        "on",
        "with",
        "that",
        "this",
        "it",
        "as",
        "at",
        "by",
        "from",
        "not",
        "have",
        "has",
        "had",
        "but",
        "they",
        "you",
        "we",
        "he",
        "she",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "do",
        "does",
        "did",
        "their",
        "its",
        "our",
        "your",
        "all",
        "each",
        "which",
        "there",
        "when",
        "what",
        "who",
        "how",
        "than",
        "then",
        "if",
        "no",
        "yes",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "also",
        "after",
        "before",
        "between",
        "during",
        "under",
        "over",
        "about",
        "into",
        "out",
        "up",
        "down",
    ]
)
_EN_RATIO_THRESHOLD = 0.08
_MIN_TOKENS_FOR_LANGUAGE = 20

_BOILERPLATE_LINE_RES = (
    re.compile(r"^\s*(©|copyright\b)", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"cookie (policy|preferences|settings)", re.IGNORECASE),
    re.compile(r"^\s*(home|about us|contact|careers)(\s*[|>·]\s*\w+.*)?\s*$", re.IGNORECASE),
    re.compile(r"subscribe to our newsletter", re.IGNORECASE),
    re.compile(r"terms of (service|use)", re.IGNORECASE),
)
_MIN_DOC_CHARS = 80


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _filter_dedup(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    kept: list[Document] = []
    for doc in docs:  # docs arrive sorted by source, so "first wins" is stable
        digest = hashlib.sha1(_normalized(doc.text).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        kept.append(doc)
    return kept


def _filter_language(docs: list[Document]) -> list[Document]:
    kept: list[Document] = []
    for doc in docs:
        tokens = [t.lower() for t in _WORD_RE.findall(doc.text)]
        if len(tokens) < _MIN_TOKENS_FOR_LANGUAGE:
            kept.append(doc)
            continue
        ratio = sum(t in _EN_STOPWORDS for t in tokens) / len(tokens)
        if ratio >= _EN_RATIO_THRESHOLD:
            kept.append(doc)
    return kept


def _filter_boilerplate(docs: list[Document]) -> list[Document]:
    """Strip boilerplate lines in place (line removal only — never reflows
    surviving lines, so substring-based gold labels stay valid), then drop
    documents with too little content left."""
    kept: list[Document] = []
    for doc in docs:
        lines = [
            line
            for line in doc.text.splitlines()
            if not any(pattern.search(line) for pattern in _BOILERPLATE_LINE_RES)
        ]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        if len(text) < _MIN_DOC_CHARS:
            continue
        kept.append(doc if text == doc.text else doc.model_copy(update={"text": text}))
    return kept


def _filter_pii(docs: list[Document]) -> list[Document]:
    """Redact PII (emails, key-shaped secrets, phone numbers) in place. Drops
    nothing; the privacy suite's ``pii_filter`` defense shares this redaction."""
    kept: list[Document] = []
    for doc in docs:
        redacted = redact_pii(doc.text)
        kept.append(doc if redacted == doc.text else doc.model_copy(update={"text": redacted}))
    return kept


_FILTERS: dict[str, Callable[[list[Document]], list[Document]]] = {
    "dedup": _filter_dedup,
    "language": _filter_language,
    "boilerplate": _filter_boilerplate,
    "pii": _filter_pii,
}


def apply_filters(
    docs: list[Document], names: Sequence[FilterName]
) -> tuple[list[Document], list[FilterStats]]:
    stats: list[FilterStats] = []
    current = docs
    for name in names:
        result = _FILTERS[name](current)
        stats.append(FilterStats(name=name, dropped=len(current) - len(result)))
        current = result
    return current, stats
