"""Entailment judging for the faithfulness suite.

Two implementations behind one protocol:

- ``LlmJudge`` — judges through the provider-agnostic Generator interface with
  a versioned prompt template and a JSONL cache. Cache key =
  sha256(template_version | model | claim | context), so judgments are
  reusable across runs and invalidate when the template or judge model
  changes. Modes: ``auto`` (read, judge+persist misses), ``cached``
  (read-only; a miss is an error — full reproducibility for graders),
  ``live`` (always re-judge, refresh entries).
- ``HeuristicJudge`` — deterministic content-token containment. No model, no
  cache; what CI and the fake-provider smoke spec use. Also the fallback
  verdict when an LLM judge returns something unparseable (recorded as
  ``parse_ok=False`` rather than silently counted).

Judge quality is configuration, not a hidden constant — swap the judge in the
spec and the cache keys keep results separated.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

from crucible.config import JudgeConfig, ProviderRef
from crucible.providers import GenParams, Message, build_generator
from crucible.providers.base import Generator
from crucible.types import StrictModel

JUDGE_TEMPLATE_VERSION = "entail-v1"

_JUDGE_SYSTEM = (
    "You judge whether a claim is supported by a context. Answer with exactly "
    "one word: YES if the context supports the claim, NO if it does not."
)
_JUDGE_USER = "Context:\n{context}\n\nClaim: {claim}\n\nSupported? Answer YES or NO:"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEURISTIC_THRESHOLD = 0.7


class JudgeVerdict(StrictModel):
    supported: bool
    parse_ok: bool
    cached: bool


class JudgeCacheMissError(Exception):
    """mode=cached and a judgment is missing — re-run with mode=auto/live."""


class EntailmentJudge(Protocol):
    name: str

    async def supports(self, claim: str, context: str) -> JudgeVerdict: ...


def _heuristic_supported(claim: str, context: str) -> bool:
    claim_tokens = set(_TOKEN_RE.findall(claim.lower()))
    if not claim_tokens:
        return True
    context_tokens = set(_TOKEN_RE.findall(context.lower()))
    return len(claim_tokens & context_tokens) / len(claim_tokens) >= _HEURISTIC_THRESHOLD


class HeuristicJudge:
    name = "heuristic"

    async def supports(self, claim: str, context: str) -> JudgeVerdict:
        return JudgeVerdict(
            supported=_heuristic_supported(claim, context), parse_ok=True, cached=False
        )


class JudgeCache:
    """Append-only JSONL: one {key, supported} per line, loaded fully at open.
    Later entries win, so ``live`` mode refreshes by appending."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: dict[str, bool] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._entries[entry["key"]] = bool(entry["supported"])

    def get(self, key: str) -> bool | None:
        return self._entries.get(key)

    def put(self, key: str, supported: bool) -> None:
        self._entries[key] = supported
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "supported": supported}) + "\n")


class LlmJudge:
    def __init__(
        self,
        generator: Generator,
        *,
        model: str,
        mode: str,
        cache: JudgeCache | None,
    ) -> None:
        self.name = f"llm:{model}"
        self._generator = generator
        self._model = model
        self._mode = mode
        self._cache = cache

    def _key(self, claim: str, context: str) -> str:
        blob = f"{JUDGE_TEMPLATE_VERSION}|{self._model}|{claim}|{context}"
        return hashlib.sha256(blob.encode()).hexdigest()

    async def supports(self, claim: str, context: str) -> JudgeVerdict:
        key = self._key(claim, context)
        if self._mode != "live" and self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                return JudgeVerdict(supported=hit, parse_ok=True, cached=True)
            if self._mode == "cached":
                raise JudgeCacheMissError(
                    f"judgment missing from cache for claim {claim[:60]!r}; "
                    "re-run with judge.mode=auto to populate the cache"
                )

        messages = [
            Message(role="system", content=_JUDGE_SYSTEM),
            Message(role="user", content=_JUDGE_USER.format(context=context, claim=claim)),
        ]
        result = await self._generator.generate(
            messages, params=GenParams(temperature=0.0, max_tokens=8)
        )
        verdict_text = result.text.strip().upper()
        if verdict_text.startswith("YES"):
            supported, parse_ok = True, True
        elif verdict_text.startswith("NO"):
            supported, parse_ok = False, True
        else:  # unparseable judge output: heuristic fallback, honestly flagged
            supported, parse_ok = _heuristic_supported(claim, context), False
        if self._cache is not None:
            self._cache.put(key, supported)
        return JudgeVerdict(supported=supported, parse_ok=parse_ok, cached=False)


def build_judge(config: JudgeConfig) -> EntailmentJudge:
    if config.kind == "heuristic":
        return HeuristicJudge()
    assert config.provider is not None and config.model is not None  # validated by JudgeConfig
    generator = build_generator(ProviderRef(provider=config.provider, model=config.model))
    cache = JudgeCache(config.cache) if config.cache is not None else None
    return LlmJudge(generator, model=config.model, mode=config.mode, cache=cache)
