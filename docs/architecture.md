# rag-crucible — Architecture

Companion to [DESIGN.md](DESIGN.md). This file holds the diagrams and the
stage-by-stage data contracts; the rationale behind every decision lives in DESIGN.md.

---

## 1. System context

```mermaid
flowchart LR
    subgraph clients [Clients]
        CLI[crucible CLI]
        DASH[Dashboard<br/>Vite + React SPA]
    end

    subgraph services [Services]
        API[FastAPI<br/>api/]
        WORKER[Eval Worker<br/>crucible.runner]
    end

    subgraph core [Core library: crucible/]
        INGEST[ingest<br/>loaders · filters · chunkers]
        PIPE[pipeline<br/>retrieve → rerank → generate]
        EVAL[eval suites<br/>retrieval · faithfulness · security · privacy]
        ATTACKS[attacks<br/>poison docs · injections · canaries]
        PROV[providers<br/>cohere · local · openai · fake]
        IDX[index<br/>FAISS · Qdrant]
    end

    subgraph storage [Storage]
        DB[(SQLite<br/>result store + job queue)]
        VS[(Vector index<br/>FAISS files / Qdrant)]
    end

    CLI --> INGEST & PIPE & EVAL
    DASH -->|HTTP| API
    API -->|enqueue / read| DB
    API -->|/query| PIPE
    WORKER -->|claim jobs| DB
    WORKER --> EVAL
    EVAL --> ATTACKS
    EVAL --> PIPE
    INGEST --> PROV
    PIPE --> PROV
    PIPE --> IDX
    INGEST --> IDX
    IDX --> VS
    WORKER -->|persist results| DB
```

The CLI, API, and worker are thin shells over one core library. The dashboard is a
read-only HTTP client of the API. Evaluation logic exists in exactly one place:
`crucible/eval/`.

---

## 2. Ingestion pipeline

```mermaid
flowchart LR
    SRC[/corpus dir<br/>.md .txt .pdf .html/] --> LOAD[Loaders<br/>pluggable per extension]
    LOAD -->|"Document"| FILT[Filter chain<br/>dedup → language → boilerplate → PII opt-in]
    FILT -->|"Document"| CHUNK[Chunker<br/>fixed-overlap · structure-aware]
    CHUNK -->|"Chunk"| EMB[Embedder<br/>provider interface<br/>input_type=DOCUMENT]
    EMB -->|"vectors + Chunk"| BUILD[Index builder]
    BUILD --> VS[(VectorIndex<br/>FAISS default / Qdrant)]
```

- Filters are an ordered chain of registered names; each consumes and yields
  `Document`s, so adding a filter never touches its neighbors.
- Chunk identity is deterministic (`sha1(doc_id:start:end)[:16]`), which is what lets
  gold labels, poisoned-chunk tracking, and canary tracking survive re-indexing.
- The attack suites reuse this exact pipeline to build their poisoned indexes — there
  is no second ingestion path.

---

## 3. Query path (the system under test)

```mermaid
sequenceDiagram
    participant C as Caller (CLI / API / eval suite)
    participant P as RagPipeline
    participant E as Embedder
    participant V as VectorIndex
    participant R as Reranker
    participant G as Generator

    C->>P: query(text)
    P->>E: embed([query], input_type=QUERY)
    E-->>P: vector
    P->>V: search(vector, k)
    V-->>P: list[Candidate] (k)
    alt rerank enabled
        P->>R: rerank(query, candidate texts, top_n)
        R-->>P: ranking (indices + scores)
    else rerank disabled
        P->>P: truncate to top_n by retrieval score
    end
    P->>P: build prompt (defense toggles apply here)
    P->>G: generate(messages, params)
    G-->>P: text + usage
    P->>P: parse citation markers → Citation[]
    P-->>C: Answer{text, citations, context, usage, timings}
```

Every stage is wrapped in a `StageTimer`; the `Answer` carries per-stage wall time and
token usage, which the runner aggregates into p50/p95 per run.

Defense toggles live in the prompt-build step (`prompt_isolation`) and between
retrieval and prompt-build (`injection_filter` screens candidate chunks) — both are
config flags on `pipeline.defenses`, so the security suite can measure each condition
in one run.

---

## 4. Evaluation run lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending : POST /runs (spec validated)
    pending --> running : worker claims (atomic UPDATE…RETURNING)
    running --> succeeded : all suites complete
    running --> failed : any suite fails (completed suites persisted)
    pending --> cancelled : DELETE /runs/{id}
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
```

```mermaid
flowchart TB
    SPEC[RunSpec YAML] -->|parse + validate| RS[RunSpec pydantic]
    RS -->|canonical JSON + hash| DB[(runs table)]
    DB -->|claim| W[Worker]
    W --> S1[retrieval suite] & S2[faithfulness suite] & S3[security suite] & S4[privacy suite]
    S1 & S2 & S3 & S4 -->|Metric + EvalRecord| AGG[Aggregate + persist]
    AGG --> DB2[(metrics · records · suite_results · stage_timings)]
    DB2 --> APIQ[GET /runs/:id/results] --> DASHV[Dashboard]
```

Suites run concurrently (they are independent by construction); items within a suite
run through a bounded asyncio pool sized to provider rate limits.

---

## 5. Module dependency graph (allowed imports)

```mermaid
flowchart BT
    types[crucible.types + crucible.config]
    providers[crucible.providers] --> types
    index[crucible.index] --> types
    ingest[crucible.ingest] --> types & providers & index
    pipeline[crucible.pipeline] --> providers & index & types
    attacks[crucible.attacks] --> types & ingest
    eval[crucible.eval] --> pipeline & attacks & types
    runner[crucible.runner] --> eval & pipeline & ingest & types
    api[api/ Phase 3] --> runner
    cli[crucible CLI] --> runner & pipeline & ingest & types
```

Arrows mean "may import". Anything not drawn is forbidden — in particular, `eval` may
not import `providers` directly (it consumes the pipeline's public interface only),
and nothing imports from `api/`. `ingest` imports `index` because ingestion *ends* by
building the index (`ingest/build.py`) — there is exactly one index-build path, and
the attack suites reuse it for their poisoned indexes.

---

## 6. Data contracts

The full table and identity rules are in [DESIGN.md §3](DESIGN.md#3-data-contracts-between-stages);
this is the wire-level view of the chain:

```
Document        {doc_id, source, text, meta}
   │  filters (Document → Document)
Chunk           {chunk_id, doc_id, text, start, end, section, tags}
   │  embed(input_type=DOCUMENT)
IndexItem       {chunk_id, vector, payload=Chunk}
   │  search(query_vector, k)
Candidate       {chunk, score, rank}
   │  rerank(query, docs, top_n)   [optional]
RankedContext   {candidates[top_n], rerank_applied}
   │  prompt build (+ defenses) → generate
Answer          {text, citations[], context, usage, timings}
   │  eval suites
EvalRecord      {kind, query_id, payload}      → records table
Metric          {suite, name, variant, value}  → metrics table
SuiteResult     {suite, metrics[], records[]}  → suite_results table
RunResult       {run_id, spec, suite_results, timings}
```

All of these are frozen pydantic models: `Document`/`Chunk` live in `crucible/types.py`
(the dependency root, importable by every module), pipeline-owned models in
`crucible/pipeline/types.py`. Provider-facing results (`EmbedResult`, `RerankResult`,
`GenerateResult`, `Usage`) are defined with the provider interface in
[DESIGN.md §4](DESIGN.md#4-the-provider-abstraction-the-most-important-contract).
