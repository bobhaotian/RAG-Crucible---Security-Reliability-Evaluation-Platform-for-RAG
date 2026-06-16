"""Privacy suite end-to-end on the fake provider: canary leakage, the
retrieval-exposure vs generation-leakage decomposition, and the pii_filter
defense driving leakage to zero."""

from __future__ import annotations

from pathlib import Path

from crucible.config import PrivacySuiteConfig, RunSpec, SuitesConfig
from crucible.eval import EvalRunResult, PrivacyRecord, run_eval
from crucible.eval.report import write_report
from crucible.index import FaissIndex
from crucible.ingest import build_index

from ..conftest import make_fake_spec


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
