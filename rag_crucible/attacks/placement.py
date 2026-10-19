"""Corpus-shaped source paths for generated attack and canary documents.

A generated document needs a source path, and that path is not private to the
evaluator: ``format_context_block`` prints it into every prompt that retrieves
the chunk, and every defense receives it on the chunk. A path that names the
test (``__poison__/q007.md``) tells the generator and the defenses which
passage is the attack, an answer key no deployed system is given. On
Qwen2.5-0.5B, hiding the canary path alone moved privacy leakage under no
defense from 5/27 to 10/27 (one run, exact McNemar p = 0.0625): the model reads
the path, though the size of the effect is not established. (That run
replaced the marker with a neutral hex name in ``kb/``, not with the scheme
below, which has no real-model measurement of its own yet.)

So a generated document is placed the way a contributed one would be: in one
of the corpus's own top-level directories, named by a slug of its own topic.
The attack on "What is the Fleet Manager API rate limit?" becomes a name like
``<dir>/fleet-manager-api-rate.md``, the same kind of name as the corpus's own
``kb/api-rate-limits.md``. The evaluator tracks planted documents by ``doc_id``
and never needs the path.

A planted name never shares a stem with another planted document or a corpus
file, and never forms a numbered pair with one: when the poison and the
injection on one question both want ``x.md``, ``x-2.md`` beside ``x.md`` would
mark the second as the copy. Each document draws its own seeded order over
windows of its topic's words, then those windows with a neutral qualifier
(``parental-leave-policy``, the way the corpus has ``at-300-spec``), then
neutral names, so twins get different, equally plausible names. A number is
appended only when every one of those is taken.

The name still comes from the topic, which for an attack is the target
question; only an opaque per-chunk label in the prompt removes that from the
generator's view (``docs/threat-model.md``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Iterator

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

# Names for a topic with no Latin-script words to slug, such as Chinese. Drawn
# in a seeded order, so a run of them is not notes, notes-2, notes-3.
_NEUTRAL_NAMES = (
    "overview",
    "reference",
    "summary",
    "details",
    "guide",
    "notes",
    "update",
    "faq",
    "policy",
    "procedure",
    "handbook",
    "background",
)


def _content_words(topic: str, hide: Iterable[str] = ()) -> list[str]:
    """The topic's words a person would name a file by, folded to ASCII.

    Accents are folded rather than split on ("cuál" -> ``cual``); hyphenated
    codes stay whole ("AT-300" -> ``at-300``), the way a hand-written name
    keeps them. ``hide`` drops words that would identify the document to the
    system under test, such as a qid that appears in the question text.
    """
    folded = unicodedata.normalize("NFKD", topic.lower())
    ascii_text = "".join(ch for ch in folded if not unicodedata.combining(ch))
    hidden = {word.lower() for word in hide}
    return [
        word
        for word in _WORD_RE.findall(ascii_text)
        if word not in _STOP_WORDS
        and word not in hidden
        and not any(stem in word for stem in _MARKER_STEMS)
    ]


def _join(words: list[str]) -> str:
    kept: list[str] = []
    for word in words[:_MAX_WORDS]:
        if kept and len("-".join([*kept, word])) > _MAX_SLUG_CHARS:
            break
        kept.append(word)
    return "-".join(kept)[:_MAX_SLUG_CHARS].strip("-")


def slug(topic: str) -> str:
    """A short, lowercase, hyphenated name from a topic's leading content words,
    or ``""`` when it has none."""
    return _join(_content_words(topic))


def _candidate_names(seed: int, key: str, topic: str, hide: Iterable[str]) -> Iterator[str]:
    """Every name the document may take, best first, each tier in an order
    seeded by key: windows of 4, 3 and 2 consecutive content words; then each
    window with a neutral qualifier; then the neutral names on their own.
    """

    def seeded(names: Iterable[str]) -> list[str]:
        return sorted(dict.fromkeys(names), key=lambda name: _score(seed, f"{key}\0{name}"))

    words = _content_words(topic, hide)
    windows = [
        _join(words[start : start + size])
        for size in (_MAX_WORDS, 3, 2)
        for start in range(max(1, len(words) - size + 1))
    ]
    windows = [name for name in windows if name]
    yield from seeded(windows)
    yield from seeded(
        f"{window}-{qualifier}"
        for window in windows
        for qualifier in _NEUTRAL_NAMES
        if len(window) + 1 + len(qualifier) <= _MAX_SLUG_CHARS
    )
    yield from seeded(_NEUTRAL_NAMES)


_NUMBERED_STEM = re.compile(r"^(.+)-\d+$")


class CorpusPlacer:
    """Assigns collision-free, corpus-shaped paths, one document at a time.

    ``corpus_sources`` are the sources of the corpus the documents will be
    indexed beside, and set the directories a document may land in. ``avoid``
    adds paths a document must not take without offering their directories,
    such as corpus files the ingest filters dropped, or documents placed by
    another generator into the same index. Every placed path is remembered, so
    a later placement avoids it, and its file name, too.
    """

    def __init__(
        self, corpus_sources: Iterable[str], seed: int, *, avoid: Iterable[str] = ()
    ) -> None:
        sources = list(corpus_sources)
        self._seed = seed
        # Compared case-folded: on a case-insensitive filesystem kb/FAQ.md and
        # kb/faq.md are the same file, so a placement must not take either.
        self._taken = {source.lower() for source in [*sources, *avoid]}
        # File-name stems already in use anywhere, and the bases of those that
        # end in a number, so a placement neither repeats one nor pairs with one.
        self._stems: set[str] = set()
        self._numbered_bases: set[str] = set()
        for path in [*sources, *avoid]:
            self._note(path)
        self._locations = _locations(sources)

    def place(self, key: str, topic: str, *, hide: Iterable[str] = ()) -> str:
        """Return a fresh path for the document identified by ``key``.

        ``key`` only seeds the choices, so one document lands in the same place
        on every run; it never appears in the path, and neither does any word
        in ``hide``. Give each generator its own keys ("poison:q001",
        "injection:q001"), so twins on one question draw different orders.
        """
        location = self._locations[_score(self._seed, key) % len(self._locations)]
        prefix = f"{location}/" if location else ""
        fallback = ""
        for name in _candidate_names(self._seed, key, topic, hide):
            path = f"{prefix}{name}.md"
            fallback = fallback or name
            if path.lower() not in self._taken and self._free(name):
                return self._take(path)
        # Every topical and neutral name is taken; only now count.
        suffix = 2
        while f"{prefix}{fallback}-{suffix}.md".lower() in self._taken:
            suffix += 1
        return self._take(f"{prefix}{fallback}-{suffix}.md")

    def _free(self, stem: str) -> bool:
        """Neither in use nor one half of a numbered pair with a name in use."""
        if stem in self._stems or stem in self._numbered_bases:
            return False
        numbered = _NUMBERED_STEM.match(stem)
        return not (numbered and numbered.group(1) in self._stems)

    def _note(self, path: str) -> None:
        stem = _stem(path)
        self._stems.add(stem)
        numbered = _NUMBERED_STEM.match(stem)
        if numbered:
            self._numbered_bases.add(numbered.group(1))

    def _take(self, path: str) -> str:
        self._taken.add(path.lower())
        self._note(path)
        return path


def _stem(path: str) -> str:
    """The file name without its directory or extension, case-folded."""
    name = path.rpartition("/")[2].lower()
    return name.rpartition(".")[0] if "." in name else name


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
