"""The crucible API (DESIGN.md §8): a thin shell over the runner and store.

No evaluation logic lives here. Endpoints:

    POST   /runs                submit a RunSpec (JSON body) → run id (202)
    GET    /runs                list runs
    GET    /runs/{id}           status row
    GET    /runs/{id}/results   metrics, suite summaries, stage timings
    GET    /runs/{id}/records   per-item evidence, paginated
    DELETE /runs/{id}           cancel a pending run
    POST   /query               live answer through the serving pipeline
    GET    /health

The serving pipeline comes from one spec (``CRUCIBLE_SERVE_SPEC``, default
specs/smoke-fake.yaml so a keyless `docker compose up` answers instantly); it
is built lazily on first /query — including building the index if missing.
Execution of submitted runs belongs to the worker process, never the API.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Query, Response
from pydantic import ValidationError

from api.schemas import (
    CitationOut,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    RecordsPage,
    SubmitRunResponse,
)
from crucible.config import RunSpec, load_spec
from crucible.ingest import load_or_build_index
from crucible.paths import default_db_path
from crucible.pipeline import RagPipeline, build_pipeline
from crucible.providers import ProviderError
from crucible.runner import (
    DuplicateRunError,
    ResultStore,
    RunNotFoundError,
    RunResults,
    RunRow,
)

DEFAULT_SERVE_SPEC = "specs/smoke-fake.yaml"


class ServingPipeline:
    """Lazily built, lock-guarded singleton around the configured pipeline."""

    def __init__(self, spec_path: Path) -> None:
        self.spec_path = spec_path
        self._pipeline: RagPipeline | None = None
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    async def get(self) -> RagPipeline:
        async with self._lock:
            if self._pipeline is None:
                spec = load_spec(self.spec_path)
                index = await load_or_build_index(spec)
                self._pipeline = build_pipeline(spec, index)
        return self._pipeline


def create_app(*, db_path: Path | None = None, serve_spec_path: Path | None = None) -> FastAPI:
    store = ResultStore(db_path if db_path is not None else default_db_path())
    serving = ServingPipeline(
        serve_spec_path
        if serve_spec_path is not None
        else Path(os.environ.get("CRUCIBLE_SERVE_SPEC", DEFAULT_SERVE_SPEC))
    )

    app = FastAPI(
        title="rag-crucible",
        description="Security, faithfulness, and privacy evaluation for RAG pipelines.",
        version="0.1.0",
    )

    @app.post("/runs", status_code=202, response_model=SubmitRunResponse)
    def submit_run(
        spec_body: Annotated[dict[str, Any], Body()],
        force: Annotated[bool, Query()] = False,
    ) -> SubmitRunResponse:
        try:
            spec = RunSpec.model_validate(spec_body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if spec.suites is None:
            raise HTTPException(status_code=422, detail="spec configures no `suites:`")
        try:
            run_id = store.submit_run(spec, force=force)
        except DuplicateRunError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SubmitRunResponse(run_id=run_id, status="pending")

    @app.get("/runs", response_model=list[RunRow])
    def list_runs(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[RunRow]:
        return store.list_runs(limit=limit)

    @app.get("/runs/{run_id}", response_model=RunRow)
    def get_run(run_id: str) -> RunRow:
        try:
            return store.get_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc

    @app.get("/runs/{run_id}/results", response_model=RunResults)
    def get_results(run_id: str) -> RunResults:
        try:
            return store.get_results(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc

    @app.get("/runs/{run_id}/records", response_model=RecordsPage)
    def get_records(
        run_id: str,
        suite: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RecordsPage:
        try:
            records = store.get_records(run_id, suite=suite, limit=limit, offset=offset)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc
        return RecordsPage(run_id=run_id, suite=suite, offset=offset, limit=limit, records=records)

    @app.delete("/runs/{run_id}")
    def cancel_run(run_id: str) -> Response:
        try:
            cancelled = store.cancel_run(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no run {run_id}") from exc
        if not cancelled:
            raise HTTPException(
                status_code=409, detail="run already left the queue; only pending runs cancel"
            )
        return Response(status_code=204)

    @app.post("/query", response_model=QueryResponse)
    async def query(request: QueryRequest) -> QueryResponse:
        try:
            pipeline = await serving.get()
            answer = await pipeline.answer(request.question)
        except ProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        by_marker = {
            i: candidate.chunk for i, candidate in enumerate(answer.context.candidates, start=1)
        }
        citations = [
            CitationOut(
                marker=c.marker,
                chunk_id=c.chunk_id,
                source=by_marker[c.marker].source,
                section=by_marker[c.marker].section,
                parsed=c.parsed,
            )
            for c in answer.citations
        ]
        timings = {
            "embed_query": answer.timings.embed_query_ms,
            "retrieve": answer.timings.retrieve_ms,
            "generate": answer.timings.generate_ms,
            "total": answer.timings.total_ms,
        }
        if answer.timings.rerank_ms is not None:
            timings["rerank"] = answer.timings.rerank_ms
        return QueryResponse(
            answer=answer.text,
            citations=citations,
            timings_ms=timings,
            input_tokens=answer.usage.input_tokens,
            output_tokens=answer.usage.output_tokens,
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        store_ok = True
        try:
            store.list_runs(limit=1)
        except Exception:
            store_ok = False
        return HealthResponse(
            status="ok" if store_ok else "degraded",
            store=store_ok,
            serving_spec=str(serving.spec_path),
            pipeline_loaded=serving.loaded,
        )

    return app
