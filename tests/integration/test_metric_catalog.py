"""The metric catalog, the suites and docs/metrics.md say the same thing.

Every metric a suite can emit, measured or not, has exactly one catalog entry,
no entry describes a metric nothing emits, and each state a metric takes
without a value is one its entry names. docs/metrics.md is the catalog's
rendering, so editing one without the other fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from rag_crucible.config import (
    AttackKindConfig,
    RerankerConfig,
    SecuritySuiteConfig,
    SuitesConfig,
    load_spec,
)
from rag_crucible.eval import Metric, faithfulness, run_eval, security
from rag_crucible.eval.catalog import CATALOG, definition_for, render_markdown
from rag_crucible.eval.retrieval import run_retrieval_suite
from rag_crucible.index import FaissIndex
from rag_crucible.ingest import build_index
from rag_crucible.obs.aggregate import TimingCollector
from rag_crucible.qa import QAItem

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Unqueried:
    has_reranker = False


async def _emitted(tmp_path: Path) -> list[Metric]:
    """Metrics from a full smoke-fake run plus every empty-sample branch."""
    spec = load_spec(REPO_ROOT / "specs" / "smoke-fake.yaml")
    await build_index(spec, tmp_path / "index")
    index, _ = FaissIndex.load(tmp_path / "index")
    metrics = [m for s in (await run_eval(spec, index)).suites for m in s.metrics]

    # No reranker: the rerank-on variant is inapplicable.
    assert spec.suites is not None
    no_rerank = spec.model_copy(
        update={
            "pipeline": spec.pipeline.model_copy(
                update={"reranker": RerankerConfig(provider="fake", model="overlap", enabled=False)}
            ),
            "suites": SuitesConfig(retrieval=spec.suites.retrieval),
        }
    )
    metrics += [m for s in (await run_eval(no_rerank, index)).suites for m in s.metrics]

    # Nothing labelled: the suite is skipped, every metric unsupported.
    assert spec.suites.retrieval is not None
    skipped = await run_retrieval_suite(
        _Unqueried(),  # type: ignore[arg-type]
        [QAItem(qid="q1", question="?")],
        spec.suites.retrieval,
        TimingCollector(),
    )
    metrics += skipped.metrics

    # Empty samples in the other suites.
    metrics += faithfulness._aggregate([])
    metrics += security._aggregate(
        [], SecuritySuiteConfig(poisoning=AttackKindConfig(enabled=False), defenses=("none",))
    )
    return metrics


async def test_every_emitted_metric_has_one_entry_and_every_entry_is_emitted(
    tmp_path: Path,
) -> None:
    metrics = await _emitted(tmp_path)

    for m in metrics:
        matching = [d for d in CATALOG if d.matches(m.suite, m.name)]
        assert len(matching) == 1, f"{m.suite}/{m.name} matches {len(matching)} catalog entries"
    used = {definition_for(m.suite, m.name) for m in metrics}
    unused = [f"{d.suite}/{d.name}" for d in CATALOG if d not in used]
    assert not unused, f"catalog entries no suite emits: {unused}"


async def test_a_metric_without_a_value_takes_a_state_its_entry_names(tmp_path: Path) -> None:
    metrics = await _emitted(tmp_path)

    unmeasured = [m for m in metrics if m.value is None]
    assert {m.state for m in unmeasured} == {
        "unsupported",
        "inapplicable",
        "skipped",
        "not_estimable",
    }
    for m in unmeasured:
        definition = definition_for(m.suite, m.name)
        assert definition is not None
        named = set(re.findall(r"`(\w+)`", definition.when_empty))
        assert m.state in named, f"{m.suite}/{m.name} is {m.state}; its entry names {named}"
        assert m.n == 0 or m.n is None or m.state == "unsupported"


def test_the_metrics_doc_is_the_catalog() -> None:
    doc = (REPO_ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")
    assert doc == render_markdown(), "regenerate: python -m rag_crucible.eval.catalog"
