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
from crucible.eval.run import run_eval
from crucible.eval.types import (
    AttackRecord,
    CitationJudgment,
    ClaimJudgment,
    CleanDefenseRecord,
    EvalRecord,
    EvalRunResult,
    FaithfulnessRecord,
    Metric,
    PrivacyRecord,
    RetrievalRecord,
    SuiteResult,
)
from crucible.qa import QADatasetError, QAItem, answer_matches, is_relevant, load_qa

__all__ = [
    "JUDGE_TEMPLATE_VERSION",
    "AttackRecord",
    "CitationJudgment",
    "ClaimJudgment",
    "CleanDefenseRecord",
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
    "PrivacyRecord",
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
