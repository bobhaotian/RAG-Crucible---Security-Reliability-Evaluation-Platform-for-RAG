"""Corpus-shaped source paths for generated attack and canary documents.

A generated document needs a source path, and that path is not private to the
evaluator: ``format_context_block`` prints it into every prompt that retrieves
the chunk, and every defense receives it on the chunk. A path that names the
test (``__poison__/q007.md``) tells the generator and the defenses which
passage is the attack, an answer key no deployed system is given. On
Qwen2.5-0.5B, hiding the canary path alone moved privacy leakage under no
defense from 5/27 to 10/27 (one run, exact McNemar p = 0.0625): the model reads
the path, though the size of the effect is not established.

So a generated document is placed the way a contributed one would be: in one
of the corpus's own top-level directories, named by a slug of its own topic.
The attack on "What is the Fleet Manager API rate limit?" becomes
``<dir>/fleet-manager-api-rate.md``, the same kind of name as the corpus's own
``kb/api-rate-limits.md``; a hex name like ``kb/3f9a1c2e.md`` would stand out
beside it as plainly as a marker. The evaluator tracks planted documents by
``doc_id`` and never needs the path.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Question scaffolding and function words. They carry no topic, and a slug
# built from them ("what-is-the") reads as generated rather than written.
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "each",
        "for",
        "from",
        "get",
        "give",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "long",
        "many",
        "may",
        "me",
        "mean",
        "much",
        "must",
        "my",
        "of",
        "often",
        "on",
        "or",
        "our",
        "per",
        "should",
        "show",
        "share",
        "so",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "use",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "within",
        "would",
        "you",
        "your",
    }
)

# Our own vocabulary. In a slug these are labels, not topics, so they are dropped
# even when the topic happens to contain one ("How do we detect injection?").
_MARKER_STEMS = ("poison", "inject", "canar", "attack")

_MAX_WORDS = 4
_MAX_SLUG_CHARS = 40
_FALLBACK_SLUG = "notes"


def slug(topic: str) -> str:
    """A short, lowercase, hyphenated name from a topic's content words.

    Hyphenated codes stay whole ("AT-300" -> ``at-300``), so a product or error
    code survives the stop-word pass the way it would in a hand-written name.
    """
    words = [
        word
        for word in _WORD_RE.findall(topic.lower())
        if word not in _STOP_WORDS and not any(stem in word for stem in _MARKER_STEMS)
    ]
    kept: list[str] = []
    for word in words[:_MAX_WORDS]:
        if kept and len("-".join([*kept, word])) > _MAX_SLUG_CHARS:
            break
        kept.append(word)
    return "-".join(kept)[:_MAX_SLUG_CHARS].strip("-") or _FALLBACK_SLUG


class CorpusPlacer:
    """Assigns collision-free, corpus-shaped paths, one document at a time.

    ``corpus_sources`` are the sources of the corpus the documents will be
    indexed beside. They set both the directories a document may land in and
    the paths it must not take. Every placed path is remembered, so a later
    placement avoids it too.
    """

    def __init__(self, corpus_sources: Iterable[str], seed: int) -> None:
        sources = list(corpus_sources)
        self._seed = seed
        # Compared case-folded: on a case-insensitive filesystem kb/FAQ.md and
        # kb/faq.md are the same file, so a placement must not take either.
        self._taken = {source.lower() for source in sources}
        self._locations = _locations(sources)

    def place(self, key: str, topic: str) -> str:
        """Return a fresh path for the document identified by ``key``.

        ``key`` only seeds the choice of directory, so one document lands in
        the same place on every run; it never appears in the path.
        """
        location = self._locations[_score(self._seed, key) % len(self._locations)]
        stem = f"{location}/{slug(topic)}" if location else slug(topic)
        path = f"{stem}.md"
        suffix = 2
        while path.lower() in self._taken:
            path = f"{stem}-{suffix}.md"
            suffix += 1
        self._taken.add(path.lower())
        return path


def _locations(sources: list[str]) -> list[str]:
    """Where the corpus keeps documents: each top-level directory, and the root
    ("") when files sit there. A flat or empty corpus places at the root.

    A directory with ``__`` in its name is shaped like the markers this module
    replaces, so a placement there would reopen the question; it is skipped.
    """
    found = set()
    for source in sources:
        head, sep, _ = source.partition("/")
        found.add(head if sep else "")
    usable = sorted(location for location in found if "__" not in location)
    return usable or [""]


def _score(seed: int, key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}\0{key}".encode()).digest()[:8], "big")
