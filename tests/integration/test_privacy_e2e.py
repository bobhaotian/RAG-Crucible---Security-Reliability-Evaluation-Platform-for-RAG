"""Privacy suite end-to-end on the fake provider: canary leakage, the
retrieval-exposure vs generation-leakage decomposition, and the pii_filter
defense driving leakage to zero."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import rag_crucible.eval.privacy as privacy
from rag_crucible.config import PrivacySuiteConfig, RunSpec, SuitesConfig, load_spec
from rag_crucible.eval import EvalRunResult, PrivacyRecord, run_eval
from rag_crucible.eval.report import render_summary, write_report
from rag_crucible.index import FaissIndex
from rag_crucible.ingest import build_index
from rag_crucible.types import Chunk, doc_id_for

from ..conftest import make_fake_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every canary secret carries one of these (attacks/canaries.py).
SECRET_SHAPES = ("sk-canary-", "@example-corp.test", "+1-555-")


def _privacy_spec(tiny_corpus: Path, defenses: tuple[str, ...]) -> RunSpec:
    base = make_fake_spec(tiny_corpus, name="priv-fake")
    return base.model_copy(
        update={
            "suites": SuitesConfig(
                privacy=PrivacySuiteConfig(
                    canaries=6,
                    kinds=("email", "api_key", "phone"),
                    probes=("direct", "paraphrase"),
                    defenses=defenses,  # type: ignore[arg-type]
                )
            )
        }
    )


async def _run(spec: RunSpec, tmp_path: Path) -> EvalRunResult:
    index_dir = tmp_path / "index"
    if not (index_dir / "meta.json").is_file():
        await build_index(spec, index_dir)
    index, _ = FaissIndex.load(index_dir)
    return await run_eval(spec, index)


def _records(result: EvalRunResult) -> list[PrivacyRecord]:
    suite = next(s for s in result.suites if s.suite == "privacy")
    return [r for r in suite.records if isinstance(r, PrivacyRecord)]


async def test_privacy_suite_needs_no_qa_labels(tiny_corpus: Path, tmp_path: Path) -> None:
    # the spec sets no corpus.qa, yet a privacy-only run is valid and executes
    spec = _privacy_spec(tiny_corpus, ("none",))
    assert spec.corpus.qa is None
    result = await _run(spec, tmp_path)
    assert any(s.suite == "privacy" for s in result.suites)


async def test_canaries_leak_without_redaction_and_are_sealed_by_pii_filter(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    result = await _run(_privacy_spec(tiny_corpus, ("none", "pii_filter")), tmp_path)

    none_leak = result.metric("privacy", "leakage_rate", "defense=none")
    filtered_leak = result.metric("privacy", "leakage_rate", "defense=pii_filter")
    assert none_leak is not None and none_leak > 0.0  # the extractive stub leaks secrets
    assert filtered_leak == 0.0  # redaction removes the secret from the index

    # decomposition: redaction leaves retrieval exposure but kills generation leakage
    none_exposure = result.metric("privacy", "retrieval_exposure_rate", "defense=none")
    filtered_exposure = result.metric("privacy", "retrieval_exposure_rate", "defense=pii_filter")
    assert none_exposure == 1.0
    assert filtered_exposure is not None and filtered_exposure > filtered_leak


async def test_records_cover_canaries_probes_and_conditions(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    result = await _run(_privacy_spec(tiny_corpus, ("none", "pii_filter")), tmp_path)
    records = _records(result)
    # 6 canaries * 2 probe styles * 2 conditions
    assert len(records) == 6 * 2 * 2
    assert {r.defense for r in records} == {"none", "pii_filter"}
    assert {r.canary_kind for r in records} == {"email", "api_key", "phone"}
    leaked_none = [r for r in records if r.defense == "none" and r.leaked]
    assert all(not r.leaked for r in records if r.defense == "pii_filter")
    assert leaked_none  # at least one secret extracted with no defense


async def test_privacy_is_deterministic_and_reports(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = _privacy_spec(tiny_corpus, ("none", "pii_filter"))
    first = await _run(spec, tmp_path)
    second = await _run(spec, tmp_path)
    assert first.suites == second.suites

    out = tmp_path / "report"
    written = write_report(first, out)
    assert (out / "privacy.png") in written
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "## Privacy" in summary
    assert "generation leakage" in summary
    assert "Leakage by probe style" in summary


def _smoke_privacy_spec(*, pii: bool) -> RunSpec:
    """smoke-fake's privacy suite alone, optionally with `pii` in its ingest chain."""
    spec = load_spec(REPO_ROOT / "specs" / "smoke-fake.yaml")
    assert spec.suites is not None and spec.suites.privacy is not None
    filters = (*spec.ingest.filters, "pii") if pii else spec.ingest.filters
    return spec.model_copy(
        update={
            "ingest": spec.ingest.model_copy(update={"filters": filters}),
            "suites": SuitesConfig(privacy=spec.suites.privacy),
        }
    )


@pytest.fixture
def indexed(monkeypatch: pytest.MonkeyPatch) -> list[list[Chunk]]:
    """The chunks of every index the privacy suite builds, one list per condition."""
    seen: list[list[Chunk]] = []
    original = privacy.embed_into_index

    async def recording(chunks: list[Chunk], embedder: Any) -> Any:
        seen.append(list(chunks))
        return await original(chunks, embedder)

    monkeypatch.setattr(privacy, "embed_into_index", recording)
    return seen


async def test_pii_in_ingest_filters_redacts_canaries_before_indexing(
    tmp_path: Path, indexed: list[list[Chunk]]
) -> None:
    result = await _run(_smoke_privacy_spec(pii=True), tmp_path)

    assert len(indexed) == 2  # none, pii_filter
    for chunks in indexed:
        for chunk in chunks:
            assert not any(shape in chunk.text for shape in SECRET_SHAPES), chunk.source
    for condition in ("none", "pii_filter"):
        assert result.metric("privacy", "leakage_rate", f"defense={condition}") == 0.0
    assert result.metric("privacy", "canary_docs_dropped_by_filter") == 0.0
    # Redacted, not removed: the host documents are still found.
    exposure = result.metric("privacy", "retrieval_exposure_rate", "defense=none")
    assert exposure is not None and exposure > 0.9
    summary = render_summary(result)
    assert "`none` is not defense-free here" in summary
    assert "(no redaction)" not in summary
    assert "Leakage by probe style (`none` arm, canaries redacted by `ingest.filters`)" in summary

    # A result from code whose canaries skipped the filters carries no drop
    # count; its spec saying `pii` does not mean its canaries were redacted.
    old = result.model_copy(
        update={
            "suites": tuple(
                s.model_copy(
                    update={
                        "metrics": tuple(
                            m for m in s.metrics if m.name != "canary_docs_dropped_by_filter"
                        )
                    }
                )
                for s in result.suites
            )
        }
    )
    old_summary = render_summary(old)
    assert "defense-free" not in old_summary
    assert "(no redaction)" in old_summary


async def test_default_chain_privacy_numbers_match_the_committed_run(
    tmp_path: Path, indexed: list[list[Chunk]]
) -> None:
    result = await _run(_smoke_privacy_spec(pii=False), tmp_path)

    # Not vacuous: without `pii` the secrets do reach the undefended index.
    undefended = "\n".join(chunk.text for chunk in indexed[0])
    assert all(shape in undefended for shape in SECRET_SHAPES)
    committed = json.loads(
        (REPO_ROOT / "results" / "smoke-fake" / "results.json").read_text(encoding="utf-8")
    )
    expected = next(s for s in committed["suites"] if s["suite"] == "privacy")["metrics"]
    for metric in expected:
        assert result.metric("privacy", metric["name"], metric["variant"]) == metric["value"]
    assert result.metric("privacy", "canary_docs_dropped_by_filter") == 0.0
    assert "defense-free" not in render_summary(result)


async def test_a_canary_the_filters_drop_is_counted_not_probed(
    tiny_corpus: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    indexed: list[list[Chunk]],
) -> None:
    original = privacy.apply_filters_after
    dropped: list[str] = []

    def dropping_the_first(*args: Any, **kwargs: Any) -> Any:
        kept, stats = original(*args, **kwargs)
        dropped.append(kept[0].doc_id)
        return kept[1:], stats

    monkeypatch.setattr(privacy, "apply_filters_after", dropping_the_first)
    result = await _run(_privacy_spec(tiny_corpus, ("none",)), tmp_path)

    probed = {record.canary_id for record in _records(result)}
    assert len(probed) == 5 and "email-00" not in probed  # 6 planted, the first dropped
    assert result.metric("privacy", "canary_docs_dropped_by_filter") == 1.0
    assert len(_records(result)) == 5 * 2  # the denominators hold the five probed
    assert all(chunk.doc_id != dropped[0] for chunks in indexed for chunk in chunks)
    assert "Canary documents dropped by ingest filters: 1" in render_summary(result)


async def test_a_canary_duplicating_a_corpus_file_loses_to_it_whatever_its_path(
    tiny_corpus: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    indexed: list[list[Chunk]],
) -> None:
    """No monkeypatched filter: the run's own dedup drops a canary that copies
    a corpus file, although the canary's path sorts ahead of the file's."""
    returns = (tiny_corpus / "handbook" / "returns.txt").read_text(encoding="utf-8")
    original = privacy.generate_canaries
    copied: list[str] = []

    def one_copies_the_corpus(*args: Any, **kwargs: Any) -> Any:
        canaries = original(*args, **kwargs)
        source = "handbook/a-returns.md"  # sorts before handbook/returns.txt
        document = canaries[0].document.model_copy(
            update={"doc_id": doc_id_for(source, returns), "source": source, "text": returns}
        )
        copied.append(document.doc_id)
        return [replace(canaries[0], document=document), *canaries[1:]]

    monkeypatch.setattr(privacy, "generate_canaries", one_copies_the_corpus)
    result = await _run(_privacy_spec(tiny_corpus, ("none",)), tmp_path)

    assert result.metric("privacy", "canary_docs_dropped_by_filter") == 1.0
    assert "email-00" not in {record.canary_id for record in _records(result)}
    sources = {chunk.source for chunk in indexed[0]}
    assert "handbook/returns.txt" in sources  # the corpus copy is the one indexed
    assert all(chunk.doc_id != copied[0] for chunk in indexed[0])


async def test_a_privacy_suite_left_with_no_canaries_fails_rather_than_scoring(
    tiny_corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returns = (tiny_corpus / "handbook" / "returns.txt").read_text(encoding="utf-8")
    original = privacy.generate_canaries

    def all_copy_the_corpus(*args: Any, **kwargs: Any) -> Any:
        return [
            replace(
                canary,
                document=canary.document.model_copy(
                    update={
                        "doc_id": doc_id_for(f"handbook/copy-{i}.md", returns),
                        "source": f"handbook/copy-{i}.md",
                        "text": returns,
                    }
                ),
            )
            for i, canary in enumerate(original(*args, **kwargs))
        ]

    monkeypatch.setattr(privacy, "generate_canaries", all_copy_the_corpus)
    spec = _privacy_spec(tiny_corpus, ("none",))
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    result = await run_eval(spec, index, fail_fast=False)

    suite = next(s for s in result.suites if s.suite == "privacy")
    assert suite.status == "failed" and suite.metrics == ()
    assert suite.error is not None and "dropped all 6 canary documents" in suite.error
    # The error names what was dropped and by which filter, since no record will.
    assert "email-00 by dedup (duplicate_content)" in suite.error
