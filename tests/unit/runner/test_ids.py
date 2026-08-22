from __future__ import annotations

import pytest

from crucible.runner import ids as ids_module
from crucible.runner.ids import new_run_id


def test_new_run_id_encodes_time_and_randomness_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ids_module.time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(ids_module.os, "urandom", lambda size: b"\x00" * size)
    run_id = new_run_id()

    assert run_id == "01HF7YAT000000000000000000"
    assert len(run_id) == 26
