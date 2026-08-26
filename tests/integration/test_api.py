"""API surface: submit/poll/fetch through the store, live /query with lazy
index build, and the error contract (404/409/422)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.main import create_app
from crucible.runner import ResultStore, worker_loop

from .test_eval_e2e import _eval_spec


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUCIBLE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CRUCIBLE_RESULTS_DIR", str(tmp_path / "results"))


@pytest.fixture
def client(tiny_corpus: Path, tmp_path: Path) -> TestClient:
    spec = _eval_spec(tiny_corpus, tmp_path, name="api-serve")
    serve_spec = tmp_path / "serve-spec.yaml"
    serve_spec.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    app = create_app(db_path=tmp_path / "crucible.db", serve_spec_path=serve_spec)
    return TestClient(app)


def _spec_body(tiny_corpus: Path, tmp_path: Path, name: str = "api-run") -> dict[str, object]:
    spec = _eval_spec(tiny_corpus, tmp_path, name=name)
    body: dict[str, object] = json.loads(spec.canonical_json())
    return body


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["pipeline_loaded"] is False  # lazy until first /query


def test_submit_poll_results_roundtrip(
    client: TestClient, tiny_corpus: Path, tmp_path: Path
) -> None:
    submitted = client.post("/runs", json=_spec_body(tiny_corpus, tmp_path))
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]

    assert client.get(f"/runs/{run_id}").json()["status"] == "pending"
    listed = client.get("/runs").json()
    assert any(row["id"] == run_id for row in listed)

    # duplicate submission is a conflict naming the existing run
    duplicate = client.post("/runs", json=_spec_body(tiny_corpus, tmp_path))
    assert duplicate.status_code == 409
    assert run_id in duplicate.json()["detail"]

    # the worker (separate process in production) drains the queue
    import asyncio

    store = ResultStore(tmp_path / "crucible.db")
    asyncio.run(worker_loop(store, drain=True))

    assert client.get(f"/runs/{run_id}").json()["status"] == "succeeded"
    results = client.get(f"/runs/{run_id}/results").json()
    assert {s["suite"] for s in results["suites"]} == {"retrieval", "faithfulness"}
    assert any(m["name"] == "mrr" for m in results["metrics"])
    assert (tmp_path / "results" / "api-run" / run_id / "results.json").is_file()

    page = client.get(f"/runs/{run_id}/records", params={"suite": "retrieval", "limit": 2}).json()
    assert len(page["records"]) == 2
    assert page["records"][0]["kind"] == "retrieval"


def test_cancel_pending_run(client: TestClient, tiny_corpus: Path, tmp_path: Path) -> None:
    run_id = client.post("/runs", json=_spec_body(tiny_corpus, tmp_path, name="api-cancel")).json()[
        "run_id"
    ]
    assert client.delete(f"/runs/{run_id}").status_code == 204
    assert client.get(f"/runs/{run_id}").json()["status"] == "cancelled"
    assert client.delete(f"/runs/{run_id}").status_code == 409  # no longer pending


def test_validation_and_not_found(client: TestClient) -> None:
    assert client.post("/runs", json={"name": "x", "bogus": 1}).status_code == 422
    assert client.get("/runs/NOPE").status_code == 404
    assert client.get("/runs/NOPE/results").status_code == 404
    assert client.get("/runs/NOPE/records").status_code == 404
    assert client.delete("/runs/NOPE").status_code == 404


def test_query_builds_index_lazily_and_cites(client: TestClient) -> None:
    response = client.post(
        "/query", json={"question": "What is the battery life of the Widget X1?"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "72 hours" in payload["answer"]
    assert payload["citations"], "answer must carry citations"
    assert payload["citations"][0]["source"].startswith("products/")
    assert payload["timings_ms"]["total"] > 0
    assert client.get("/health").json()["pipeline_loaded"] is True
