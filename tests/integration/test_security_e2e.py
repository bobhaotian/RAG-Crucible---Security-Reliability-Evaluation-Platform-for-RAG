"""Security suite end-to-end on the fake provider: poisoned index, defense
variants, deterministic attack-success measurement."""

from __future__ import annotations

import json
from pathlib import Path

from crucible.config import AttackKindConfig, RunSpec, SecuritySuiteConfig, SuitesConfig
from crucible.eval import AttackRecord, EvalRunResult, run_eval
from crucible.eval.report import write_report
from crucible.index import FaissIndex
from crucible.ingest import build_index

from ..conftest import make_fake_spec
from .test_eval_e2e import TINY_QA


def _security_spec(tiny_corpus: Path, tmp_path: Path, defenses: tuple[str, ...]) -> RunSpec:
    qa_path = tmp_path / "qa.jsonl"
    qa_path.write_text("\n".join(json.dumps(row) for row in TINY_QA) + "\n", encoding="utf-8")
    base = make_fake_spec(tiny_corpus, name="sec-fake")
    return base.model_copy(
        update={
            "corpus": base.corpus.model_copy(update={"qa": qa_path}),
            "suites": SuitesConfig(
                security=SecuritySuiteConfig(
                    poisoning=AttackKindConfig(targets=3),
                    injection=AttackKindConfig(targets=3),
                    defenses=defenses,  # type: ignore[arg-type]
                )
            ),
        }
    )


async def _run(spec: RunSpec, tmp_path: Path) -> EvalRunResult:
    index_dir = tmp_path / "index"
    if not (index_dir / "meta.json").is_file():
        await build_index(spec, index_dir)
    index, _ = FaissIndex.load(index_dir)
    return await run_eval(spec, index)


def _records(result: EvalRunResult) -> list[AttackRecord]:
    suite = next(s for s in result.suites if s.suite == "security")
    return [r for r in suite.records if isinstance(r, AttackRecord)]


async def test_security_suite_runs_all_conditions(tiny_corpus: Path, tmp_path: Path) -> None:
    defenses = ("none", "prompt_isolation", "injection_filter")
    result = await _run(_security_spec(tiny_corpus, tmp_path, defenses), tmp_path)
    records = _records(result)

    # 3 poison + 3 injection, each under 3 defense conditions
    assert len(records) == (3 + 3) * 3
    assert {r.defense for r in records} == set(defenses)
    assert {r.attack_type for r in records} == {"poison", "injection"}

    metric_names = {(m.name, m.variant) for s in result.suites for m in s.metrics}
    assert ("poison_retrieval_rate", "") in metric_names
    assert ("injection_retrieval_rate", "") in metric_names
    for d in defenses:
        assert ("knowledge_corruption_rate", f"defense={d}") in metric_names
        assert ("injection_compliance_rate", f"defense={d}") in metric_names
        assert ("poison_compromise_rate", f"defense={d}") in metric_names
        assert ("injection_compromise_rate", f"defense={d}") in metric_names
        assert ("attack_competition_rate", f"defense={d}") in metric_names
        assert ("cross_question_contamination_rate", f"defense={d}") in metric_names
        assert ("attack_abstention_rate", f"defense={d}") in metric_names
        assert ("clean_abstention_rate", f"defense={d}") in metric_names
        assert ("clean_answer_accuracy", f"defense={d}") in metric_names


async def test_compromise_rate_is_never_below_the_attack_it_generalises(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    """A succeeded attack is by definition a compromised trial.

    Both rates share a denominator (the trials of one attack type under one
    defense), so compromise can only ever be greater than or equal to success —
    the excess is trials hijacked by a co-resident attack.
    """
    defenses = ("none", "prompt_isolation", "injection_filter")
    result = await _run(_security_spec(tiny_corpus, tmp_path, defenses), tmp_path)
    for d in defenses:
        for success, compromise in (
            ("knowledge_corruption_rate", "poison_compromise_rate"),
            ("injection_compliance_rate", "injection_compromise_rate"),
        ):
            hit = result.metric("security", success, f"defense={d}")
            any_marker = result.metric("security", compromise, f"defense={d}")
            assert hit is not None and any_marker is not None
            assert any_marker >= hit

    for r in _records(result):
        assert r.compromised >= r.succeeded
        # own marker present iff scored a success
        assert r.succeeded == any(m.marker == r.own_marker for m in r.matched_markers)
        # foreign markers partition cleanly into same-question and other-question
        assert set(r.foreign_markers) == set(r.competing_markers) | set(r.cross_question_markers)
        if r.foreign_markers:
            assert r.compromised


async def test_attacks_are_retrieved_and_poison_corrupts(tiny_corpus: Path, tmp_path: Path) -> None:
    result = await _run(_security_spec(tiny_corpus, tmp_path, ("none",)), tmp_path)
    # the crafted docs echo the question, so they out-compete for retrieval
    assert result.metric("security", "injection_retrieval_rate") == 1.0
    assert result.metric("security", "poison_retrieval_rate") == 1.0
    # the extractive fake generator repeats the planted false value
    corruption = result.metric("security", "knowledge_corruption_rate", "defense=none")
    assert corruption is not None and corruption > 0.0


async def test_injection_filter_removes_injected_chunks(tiny_corpus: Path, tmp_path: Path) -> None:
    result = await _run(
        _security_spec(tiny_corpus, tmp_path, ("none", "injection_filter")), tmp_path
    )
    records = _records(result)
    injection = [r for r in records if r.attack_type == "injection"]
    none_retrieved = [r.retrieved for r in injection if r.defense == "none"]
    assert any(none_retrieved)  # retrievable without the defense

    # Scoped to the family the filter's patterns were written for. Asserting it
    # screens *every* injection was only ever true because every payload was one
    # of the two the regexes encode; held-out phrasings get through, and that gap
    # is reported as injection_screened_rate@heldout rather than hidden here.
    filtered_seen = [
        r.retrieved
        for r in injection
        if r.defense == "injection_filter" and r.attack_family == "seen"
    ]
    assert filtered_seen and not any(filtered_seen)
    # the defense cannot help poison (not syntactically adversarial): identical
    assert result.metric("security", "knowledge_corruption_rate", "defense=none") == result.metric(
        "security", "knowledge_corruption_rate", "defense=injection_filter"
    )


async def test_answer_integrity_runs_without_an_oracle_label(
    tiny_corpus: Path, tmp_path: Path
) -> None:
    result = await _run(
        _security_spec(tiny_corpus, tmp_path, ("none", "answer_integrity")), tmp_path
    )

    # The fake provider is a conformance check, not evidence that the defense
    # works. Attack documents now share the normal corpus channel, so the test
    # must not encode the old perfect-oracle outcome.
    assert (
        result.metric("security", "knowledge_corruption_rate", "defense=answer_integrity")
        is not None
    )
    assert (
        result.metric("security", "clean_abstention_rate", "defense=answer_integrity") is not None
    )


async def test_security_is_deterministic_and_reports(tiny_corpus: Path, tmp_path: Path) -> None:
    spec = _security_spec(tiny_corpus, tmp_path, ("none", "prompt_isolation", "injection_filter"))
    first = await _run(spec, tmp_path)
    second = await _run(spec, tmp_path)
    assert first.suites == second.suites

    out = tmp_path / "report"
    written = write_report(first, out)
    assert (out / "security.png") in written
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "## Security" in summary
    assert "injection_compliance_rate" in summary
    assert "knowledge_corruption_rate" in summary
