from __future__ import annotations

from crucible.config import PrivacySuiteConfig
from crucible.eval.privacy import _aggregate
from crucible.eval.types import PrivacyRecord


def test_aggregate_reports_each_defense_and_baseline_probe_style() -> None:
    config = PrivacySuiteConfig(probes=("direct",), defenses=("none", "pii_filter"))
    records = [
        PrivacyRecord(
            canary_id="c1", canary_kind="email", probe_style="direct", defense="none",
            retrieved=True, leaked=True, answer="secret",
        ),
        PrivacyRecord(
            canary_id="c1", canary_kind="email", probe_style="direct",
            defense="pii_filter", retrieved=True, leaked=False, answer="redacted",
        ),
    ]
    metrics = {(m.name, m.variant): m.value for m in _aggregate(records, config)}

    assert metrics[("leakage_rate", "defense=none")] == 1.0
    assert metrics[("retrieval_exposure_rate", "defense=none")] == 1.0
    assert metrics[("leakage_rate", "defense=pii_filter")] == 0.0
    assert metrics[("retrieval_exposure_rate", "defense=pii_filter")] == 1.0
    assert metrics[("leakage_rate@direct", "")] == 1.0
