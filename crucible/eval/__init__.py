"""Evaluation suites: retrieval quality and faithfulness (security and
privacy follow in Phases 4-5)."""

from crucible.eval.judge import (
    JUDGE_TEMPLATE_VERSION,
    EntailmentJudge,
    HeuristicJudge,
    JudgeCache,
    JudgeCacheMissError,
    JudgeVerdict,
    LlmJudge,
    build_judge,
)
from crucible.eval.qa import QADatasetError, QAItem, answer_matches, is_relevant, load_qa
from crucible.eval.run import run_eval
from crucible.eval.types import (
    CitationJudgment,
    ClaimJudgment,
    EvalRecord,
    EvalRunResult,
    FaithfulnessRecord,
    Metric,
    RetrievalRecord,
    SuiteResult,
)

__all__ = [
    "JUDGE_TEMPLATE_VERSION",
    "CitationJudgment",
    "ClaimJudgment",
    "EntailmentJudge",
    "EvalRecord",
    "EvalRunResult",
    "FaithfulnessRecord",
    "HeuristicJudge",
    "JudgeCache",
    "JudgeCacheMissError",
    "JudgeVerdict",
    "LlmJudge",
    "Metric",
    "QADatasetError",
    "QAItem",
    "RetrievalRecord",
    "SuiteResult",
    "answer_matches",
    "build_judge",
    "is_relevant",
    "load_qa",
    "run_eval",
]
