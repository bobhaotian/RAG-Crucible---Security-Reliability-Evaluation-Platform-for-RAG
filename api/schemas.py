"""API request/response models. Core models (RunRow, RunResults, Answer) are
reused directly; these are the shapes that exist only at the HTTP boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from crucible.runner import RecordRow, RunStatus


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitRunResponse(StrictSchema):
    run_id: str
    status: RunStatus


class ErrorResponse(StrictSchema):
    detail: str


class RecordsPage(StrictSchema):
    run_id: str
    suite: str | None
    offset: int
    limit: int
    records: list[RecordRow]


class QueryRequest(StrictSchema):
    question: str = Field(min_length=1, max_length=4000)


class CitationOut(StrictSchema):
    marker: int
    chunk_id: str
    source: str
    section: str | None
    parsed: bool


class QueryResponse(StrictSchema):
    answer: str
    citations: list[CitationOut]
    timings_ms: dict[str, float]
    input_tokens: int
    output_tokens: int


class HealthResponse(StrictSchema):
    status: str
    store: bool
    serving_spec: str
    pipeline_loaded: bool
