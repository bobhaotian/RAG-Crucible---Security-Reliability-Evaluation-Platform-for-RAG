# RAG-Crucible improvement roadmap

> **Status:** proposed living roadmap
>
> **Last repository and ecosystem audit:** 2026-09-02
>
> **Applies to:** the current `0.1.x` codebase

This document records what RAG-Crucible should improve next, why the order matters,
and what evidence is required before an item is called complete. Completed work belongs
in the [changelog](../CHANGELOG.md); implementation design decisions should be captured
in focused ADRs or RFCs and linked from here.

Popularity is an outcome, not a feature. The project earns forks, stars, and contributors
by producing numbers people can trust, evaluating systems they already have, being safe
to run, and making useful contributions small and reviewable. That is the ordering used
below.

## Executive direction

Today, RAG-Crucible is a **managed reference-RAG laboratory**: a user supplies a local
corpus, QA labels, and a Crucible pipeline spec; Crucible filters and chunks the corpus,
builds FAISS or a Crucible-owned Qdrant collection, constructs its own RAG pipeline, and
runs four evidence-backed suites.

That is valuable, but it is not yet a universal evaluator for an existing database,
retriever, framework pipeline, or deployed RAG API. Qdrant support currently means
"Crucible stores its own index in Qdrant," not "connect safely to any existing Qdrant
collection."

The target product is:

> **Bring an existing RAG endpoint, retriever, trace, or corpus. RAG-Crucible measures
> where it fails, safely reproduces the failure, compares defenses, and turns the finding
> into a permanent regression test.**

The built-in pipeline should remain as a high-quality reference implementation and
fully local demo. It should become one system-under-test adapter, not a prerequisite for
using the evaluator.

RAG-Crucible evaluates **RAG behavior**, not a database in isolation. Direct vector-store
adapters matter, but a raw database query can miss query rewriting, hybrid search,
metadata filters, authorization, reranking, and generation behavior in the real system.
Generic retriever and end-to-end target contracts therefore come before a long list of
database logos.

## Verified current boundary

| Capability | Current support | Important boundary |
|---|---:|---|
| Local `.txt`, `.md`, `.html`, and `.pdf` corpus | Yes | Corpus source is a local directory. |
| JSONL QA labels | Yes | Retrieval scoring is binary first-hit today. |
| Crucible-managed FAISS pipeline | Yes | This is the most complete path. |
| Crucible-managed Qdrant pipeline | Yes | Collection name and payload schema are owned by Crucible. |
| Existing user-owned Qdrant collection | No | Rebuild logic is not a read-only attachment lifecycle. |
| Existing BM25, hybrid, or hosted retriever | No | The current pipeline always embeds, then performs vector search. |
| Existing LangChain, LlamaIndex, or Haystack RAG | No | No public system-under-test adapter exists. |
| Black-box RAG HTTP endpoint | No | The OpenAI-compatible provider is a model provider, not a complete RAG target. |
| Custom implementations through Python internals | Partial | Useful protocols exist, but YAML/CLI registries are closed and hard-coded. |
| Retrieval, faithfulness, security, and privacy evidence | Yes | Some metric and execution semantics need the P0 fixes below. |
| CLI/worker artifacts plus SQLite/dashboard persistence | Yes | Official worker runs persist to both result surfaces. |
| Safe mutation of a production index | No | This must remain prohibited; attacks require a verified sandbox. |

The strongest foundations to preserve are the typed provider and index protocols, strict
spec validation, deterministic fake provider, local-first execution, per-item evidence,
isolated in-memory attack variants, result artifacts, worker/API path, dashboard, and
green lint/type/test/build CI.

## Non-negotiable design principles

1. **Measurement integrity before metric count.** A small valid suite is more useful than
   a large collection of weak or mislabeled scores.
2. **Never invent a zero.** Unsupported, unobserved, skipped, judge-error, and true zero
   are different states in the schema, reports, API, and dashboard.
3. **No mutation without proved ownership.** Connected targets are read-only by default.
   Corpus poisoning and canary seeding require a run-owned sandbox.
4. **Compare like with like.** A defense comparison uses paired inputs and records every
   execution difference, including backend, filters, prompt, model, and concurrency.
5. **Evidence before conclusions.** Every aggregate exposes its numerator, denominator,
   exclusions, uncertainty, and item-level records.
6. **Stable contracts before integrations.** Build generic target and plugin contracts,
   their conformance tests, and version policy before adding many one-off adapters.
7. **Local and private by default.** No telemetry by default; hosted-provider data egress
   and secrets handling must be explicit and auditable.
8. **Failures become regression assets.** A reviewed failure should be easy to freeze,
   version, commit, and replay in CI.

## Roadmap at a glance

| Order | Milestone | Exit gate |
|---:|---|---|
| P0-A | Trustworthy results | Data identity, metric meaning, backend fidelity, uncertainty, and judge quality are auditable. |
| P0-B | Bring your own RAG kernel | Native, callable, HTTP, retriever, and offline targets use capability-aware suites safely. |
| P1-A | Regression-native evaluation | Teams can set policies, compare a baseline, fail CI, and promote findings into tests. |
| P1-B | Extension ecosystem | Third-party adapters and data packs install without core edits and pass a conformance kit. |
| P1-C | Open-source release readiness | Installation, docs, governance, security reporting, releases, and compatibility claims are dependable. |
| P2 | Broader integrations and research depth | Framework/database adapters and new attacks build on the stable kernel and trusted metrics. |

Community and documentation basics can proceed in parallel, but no compatibility or
marketing claim should get ahead of the P0 exit gates.

## P0-A — trustworthy results

### 1. Content-addressed run provenance

**Current risk:** `spec_hash` and `ingest_fingerprint` hash serialized configuration,
including path strings, but not the bytes behind the corpus and QA paths. Editing a file
in place can reuse a stale index and can be deduplicated as the same submitted run.
Relative paths are also interpreted from the process working directory rather than the
spec file's directory. A YAML spec alone cannot reproduce data or model state.

Build a versioned `RunManifest` containing:

- normalized, ordered corpus file names, sizes, and SHA-256 digests;
- QA/qrels digest and dataset/attack-pack version;
- canonical spec and spec-relative resolved paths;
- Crucible version, commit SHA, dirty-worktree flag, Python/platform details, and plugin
  versions;
- resolved provider, model, model revision when available, endpoint class, generation
  parameters, and whether the provider supports deterministic seeding;
- prompt, defense, judge rubric/parser, metric-definition, and result-schema versions;
- actual backend used by each suite and variant;
- optional hardware and dependency-lock fingerprint for performance comparisons; and
- a data-egress summary without credentials or secret values.

Keep distinct identities for configuration, dataset contents, index inputs, and complete
execution. Queue deduplication and index reuse must include the applicable content digest.

**Acceptance:** changing one corpus or QA byte changes the relevant identity; moving an
unchanged spec directory does not; a stale index is rebuilt; secrets never appear in the
manifest; and an artifact explains exactly which inputs produced it.

### 2. Standard metric semantics and explicit denominators

**Current risk:** QA accepts multiple `gold_docs`, but retrieval collapses relevance to
the first relevant rank. Under multi-relevance labels, the current `recall@k` is a hit
rate, and current nDCG is the single-relevant binary reduction. `Metric` stores only one
float. Reports cannot distinguish a real zero from no eligible records, failed judging,
or unavailable target data.

Required work:

- preserve current single-gold behavior under an accurately named `hit_rate@k` metric;
- support multiple relevant documents, graded qrels, and document- and chunk-level
  relevance;
- implement and document true Recall@k, Precision@k, HitRate@k, MRR, MAP, and nDCG@k;
- expand answer correctness beyond naive substring matching with multiple references,
  normalized exact match, token F1, unanswerable/refusal handling, and an optional
  calibrated semantic scorer;
- report answer/claim/citation coverage so an extraction failure cannot improve a score
  by disappearing from its denominator;
- add `attempted`, `eligible`, `scored`, `failed`, `skipped`, numerator, denominator,
  confidence interval, and metric-definition version to result contracts; and
- test every formula on known hand-computed vectors and at least one recognized external
  qrels fixture.

**Acceptance:** metric names match their mathematical definitions; multi-qrel fixtures
produce known reference values; every displayed aggregate reveals its sample count and
exclusions; unavailable values render as unavailable, never `0.0`.

### 3. Statistically honest comparisons

Small security samples can move by ten percentage points from one item. A bare point
estimate must not imply more certainty than the run earned.

Add:

- Wilson intervals for binary rates and bootstrap intervals for other aggregates;
- paired deltas for reranking, defenses, and candidate-vs-baseline comparisons;
- configurable repetitions and seed schedules;
- minimum-sample warnings and no-result/error-rate reporting; and
- practical-effect thresholds in addition to statistical evidence.

Conclusions must stay scoped to the evaluated corpus, attacks, models, and configuration.
If a failure rate rises under a defense, that is evidence the defense harmed that tested
condition—not proof that the defense technique is universally wrong.

**Acceptance:** reports show point estimate, interval, `n`, and paired delta where
applicable; repeated runs retain their individual records; the dashboard cannot hide an
empty or error-heavy sample behind a successful-looking aggregate.

### 4. Backend- and ingestion-faithful attack variants

**Current risk:** security and privacy currently create their temporary variants through
`embed_into_index()`, which always returns FAISS, even when the run declares Qdrant.
Injected attack/canary documents also do not traverse the identical configured filter
path as clean documents. This can make a run look like it evaluated one backend and
ingestion policy when a suite actually evaluated another.

Required work:

- introduce a backend-aware, run-scoped variant factory;
- apply and record a clearly defined ingestion policy for both clean and injected data;
- use the declared backend or label an intentional substitute prominently;
- add a live Qdrant contract test, not only mocked/in-memory coverage;
- ensure unique run-owned collections, ownership tags, leases/TTL, and cleanup; and
- record planted → indexed → retrieved → reranked → exposed → obeyed/leaked stages.

**Acceptance:** a Qdrant security run uses an isolated Qdrant collection, or refuses with
an explicit unsupported reason; it never silently falls back to FAISS; variant manifests
show filter outcomes; and no user-owned collection changes.

### 5. Measure defense benefit and clean utility together

Attack success alone cannot establish that a defense is good. Every defense condition
must run paired clean and adversarial questions and report:

- attack success/compromise and stage-specific attack coverage;
- clean retrieval quality, answer correctness, faithfulness, citation behavior, and
  refusal rate;
- false-positive/filter-drop behavior;
- latency, tokens, provider cost, and error/retry deltas; and
- the declared layer the defense is intended to protect.

Add provenance/source-trust and conflicting-document consistency defenses for factual
poisoning; pattern and prompt defenses should not be presented as solving corrupted facts.
Keep deterministic markers as high-precision evidence, then add normalized, encoded, and
semantic leakage/compliance checks with their uncertainty clearly labeled.

**Acceptance:** one defense report makes both security gain and utility cost visible on
paired records. It is impossible to rank a defense solely by attack success while hiding
clean regressions.

### 6. Calibrate judges instead of treating them as truth

The current README already shows that the small local judge under-credits good answers.
Create a versioned, human-labeled judge benchmark with development, validation, and
held-out splits. Measure agreement, class precision/recall, calibration, parsing failures,
position/order sensitivity, and stability across repetitions.

Persist the full judge observation: resolved model/revision, prompt/rubric, threshold,
temperature/seed support, parser, retries, raw structured verdict, explanation where
policy permits, cache key, cache status, and error state. Warm and time judges separately
from the system under test. Synthetic cases may broaden coverage but must not be their own
sole validator.

**Acceptance:** the default judge has a published model card against held-out human labels;
judge failures are counted; changing a rubric or model invalidates its cache; deterministic
and model-judged metrics remain visibly distinct.

### 7. Determinism, timing, cost, and result durability

The run seed currently governs sampling but is not passed into generation. Suites can run
concurrently while sharing providers and one timing collector, so correctness traffic,
attack variants, and contention can be mixed into one latency distribution.

Required work:

- pass seeds through every provider that supports them and record unsupported cases;
- separate deterministic correctness runs from sequential latency benchmarks and explicit
  load tests;
- collect timings per suite, target, variant, stage, warm/cold state, and concurrency;
- record tokens, estimated/actual cost, retries, rate limits, and provider errors;
- version the portable result schema and add SQLite migrations/idempotent persistence;
- add worker leases, heartbeat, stale-job recovery, timeout, and cancellation; and
- prevent concurrent runs with the same human-readable name from racing on one index path.

**Acceptance:** adding another suite cannot silently change a suite's seed or latency
population; a killed worker's run is recoverable; replay does not duplicate records; and
old result versions are either migrated or rejected with a clear message.

### 8. Correct documentation and artifact drift

The historical design document still describes several planned APIs and behaviors as if
they were current. Committed result snapshots can also outlive the specs and result schema
that produced them.

Required work:

- label historical design material and move current behavior into tested reference docs;
- validate all YAML snippets against the current `RunSpec` in CI;
- test CLI examples and internal links;
- add provenance/staleness banners to generated artifacts; and
- regenerate benchmark artifacts deliberately or fail an artifact-freshness check.

**Acceptance:** every documented command exists, every committed spec parses, generated
results identify their exact spec/data/schema, and the docs clearly separate shipped,
experimental, and planned functionality.

## P0-B — bring your own RAG safely

### 1. Capability-negotiated system-under-test contract

Do not make every integration impersonate `RagPipeline` or `VectorIndex`. Define small,
composable protocols (names are illustrative and should be finalized in an RFC):

- `AnswerTarget`: question → answer observation;
- `ContextTarget`: answer plus retrieved contexts/citations/usage;
- `RetrievalTarget`: raw query + `k` → ranked document IDs, text, scores, and metadata;
- `RerankAblation`: optional comparable pre/post-rerank observations;
- `VariantProvisioner`: create and clean up an isolated corpus/index/defense variant; and
- `TraceTarget`: import or emit component observations using OpenInference conventions.

Each target publishes a typed capability manifest. Each suite publishes its required and
optional capabilities. Preflight either runs a valid subset or returns a typed
`unsupported`/`skipped` status and reason.

| Evaluation | Minimum observation |
|---|---|
| Answer correctness/relevance | Answer |
| Groundedness/citation checks | Answer plus contexts/citations |
| Retrieval metrics and rerank lift | Ranked retrieval observations and stable IDs |
| Read-only query security probes | Answer, with an explicit authorization policy |
| Corpus poisoning and seeded-canary privacy | Verified isolated `VariantProvisioner` |
| Full causal diagnosis | Retrieval/generation trace or OpenInference spans |

The current `RagPipeline` becomes `ManagedRagTarget`, preserving every existing spec and
suite while orchestration is changed to receive a target rather than construct one
unconditionally.

**Acceptance:** an answer-only target can run supported answer checks while context and
retrieval metrics are marked unavailable; the native pipeline retains existing behavior;
and suite code depends on capabilities rather than a concrete pipeline class.

### 2. Explicit execution modes and safety boundaries

Support four visible modes:

1. `managed-lab`: Crucible owns corpus ingestion and temporary resources; all compatible
   suites may run.
2. `connected-read-only`: Crucible queries an existing endpoint/retriever/store and cannot
   mutate it.
3. `sandbox-provisioned`: an adapter proves it can clone/provision a run-owned namespace;
   mutation suites may run there only.
4. `offline-replay`: Crucible evaluates imported answers, contexts, qrels, or traces with
   no live target calls.

Before the service is presented as public or multi-user, add authentication, allowed
corpus roots, endpoint/provider/model allowlists, SSRF controls, request/body/queue/cost
quotas, secret references, audit logs, and sandboxed non-root workers. Today the service
should be documented as trusted/local because submitted specs can contain filesystem paths
and can trigger hosted-provider work.

Installed executable plugins must be operator-approved. Never allow an untrusted API run
to choose an arbitrary Python import path.

**Acceptance:** mutation suites refuse connected read-only/production targets; sandbox
resources carry a verifiable run ownership marker and are cleaned by lease/TTL; dry-run
shows intended reads, writes, calls, and estimated cost; secrets and canaries are redacted
from logs and ordinary artifacts.

### 3. Adapter sequence

Build adapters in this order so every later integration reuses a stable contract:

1. Extract the current pipeline as the native managed adapter.
2. Add a Python callable adapter for trusted local use.
3. Add a generic HTTP adapter with declarative request, auth-reference, retry, and response
   mappings for answer/context/source fields.
4. Add neutral JSONL/CSV offline records and OpenInference/OTLP trace import/export.
5. Add a raw-query retriever adapter so BM25, hybrid search, hosted retrieval, and
   authorization-aware application retrieval fit naturally.
6. Add a **read-only existing Qdrant** adapter with explicit URL secret reference,
   collection, named vector, payload mapping, tenant/filter policy, distance/dimension
   validation, and no create/delete behavior.
7. Add framework conveniences for LangChain, LlamaIndex, and Haystack only after the
   generic target and trace contracts stabilize.
8. Add further stores based on maintained contributor demand, not logo count: pgvector,
   Elasticsearch/OpenSearch, Pinecone, Weaviate, Milvus, and others.

Split read-only search/retrieval capabilities from mutable and managed index capabilities.
The current `VectorIndex.add()` requirement should not force a connected store to appear
writable.

**Acceptance:** a black-box example evaluates without rebuilding the user's RAG; a
read-only Qdrant contract test proves collection count/content/checksum are unchanged; an
existing hybrid retriever receives raw queries; all unsupported suite cells remain typed
and visible.

## P1-A — regression-native evaluation

Add policy and comparison primitives to the spec:

- absolute thresholds, maximum failure rates, and minimum coverage;
- candidate-versus-pinned-baseline regression budgets;
- paired comparison over stable case IDs;
- nonzero CLI exit status only for configured policy failures or invalid runs;
- JSON/JSONL, CSV, JUnit XML, and SARIF security exports;
- a maintained GitHub Action and concise annotations linking to evidence; and
- baseline approval/update as an explicit reviewed action.

Make every discovered failure promotable through this loop:

```text
discover → inspect evidence → approve → freeze stable case + tags
         → commit versioned pack → replay in CI → retire only with rationale
```

Regression cases should carry source, license, stable ID, threat/quality taxonomy, expected
observation, applicable capabilities, and version. Generated cases require human review
before becoming a gate.

**Exit gate:** a pull request can compare against a pinned baseline, fail on a meaningful
paired regression, expose the exact failing records in CI, and replay a promoted security
or quality finding deterministically.

## P1-B — extension and benchmark ecosystem

### Stable plugin SDK

Replace closed `Literal` selections and central `if/elif` registries with versioned,
operator-installed entry points for targets, retrievers/stores, model providers/judges,
loaders/chunkers, metrics/suites, attacks/defenses, and reporters. Follow standard Python
package entry-point discovery.

Each extension point needs:

- a minimal typed protocol and lifecycle contract;
- semantic compatibility/version negotiation and deprecation policy;
- configuration namespace and secret-reference rules;
- capability and data-egress declaration;
- sync/async, error, retry, timeout, and cleanup behavior;
- conformance fixtures and a standalone plugin template; and
- hosted-service allowlisting and isolation guidance.

One `pip install` plus a YAML selection should activate a trusted plugin without editing
core. A broken plugin must fail independently rather than making the core package
unimportable.

### Data-first community packs

Favor reviewable YAML/JSONL data over executable contributions for benchmark qrels,
attack cases, canaries, judge labels, and regression packs. Every pack needs a data card,
license, provenance, intended scope, limitations, stable schema, version, and integrity
digest.

Support common import/export shapes used by RAG evaluation tools and information retrieval
benchmarks. Add synthetic single- and multi-hop generation as a coverage bootstrap, but
never use synthetic generation as its own only ground truth.

### Reproducible benchmark policy

- publish exact manifests, hardware/provider context, uncertainty, and raw evidence;
- distinguish smoke/demo corpora from discriminating benchmarks;
- prevent cherry-picked headline metrics by predeclaring primary measures;
- test artifact freshness and schema compatibility in CI; and
- postpone any public leaderboard until submissions are reproducible and independently
  verifiable.

**Exit gate:** an external contributor can add either a non-executable test pack or a
separately packaged adapter, run the conformance suite locally, and submit a focused pull
request without learning Crucible internals.

## P1-C — open-source release and community readiness

### Installation and packaging

- provide normal `pip`, `pipx`, and `uv tool` installation alongside the clone-and-`make`
  developer path;
- add `crucible init`, `crucible validate`, and `crucible doctor` workflows plus a packaged
  sub-minute fake-provider demo;
- split the heavy default dependency set into a small core/CLI and explicit FAISS, local
  model, report, server/dashboard, Qdrant, and `all` extras;
- add project URLs, keywords, classifiers, one version source, wheel/sdist build tests,
  and isolated install smoke tests; and
- publish a supported Python/OS/backend/provider compatibility matrix based on tests, not
  assumptions.

### Contributor and security foundation

Add and maintain:

- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, and a lightweight
  governance/maintainers policy;
- issue forms for bugs, metric-validity reports, adapters, and benchmark packs;
- `CODEOWNERS`, scoped labels, `good first issue` slices, and an adapter-author guide;
- a concise architecture tour and first-PR path with exact lint/type/test commands;
- responsible disclosure instructions and a clear trusted-local warning for the current
  unauthenticated service; and
- `CITATION.cff` once benchmark/research claims are intended for citation.

### Releases and CI

- adopt SemVer, a dated Keep-a-Changelog format, compatibility policy, and deprecation
  windows;
- publish tagged GitHub releases and PyPI wheels/sdists through trusted publishing, with
  attestations and an SBOM;
- add package install, docs/schema/example, coverage, migration, artifact-freshness,
  dependency, and security checks;
- use deterministic dashboard installs and test declared Python/OS support;
- run scheduled local-model and live Qdrant contract tests, with optional credentialed
  provider smoke tests that never block community forks; and
- keep release status, experimental status, and roadmap status visibly separate.

### Adoption documentation

Lead the README with a short install-to-result path and a visual evidence example. Move
long benchmark interpretation into focused docs. Publish recipes for:

- managed local corpus evaluation;
- existing HTTP RAG evaluation;
- existing retriever/Qdrant read-only evaluation;
- CI policy and baseline comparison;
- authoring QA/qrels and interpreting every metric;
- building a plugin or data pack; and
- troubleshooting models, OpenMP, Qdrant, worker, cost, and privacy concerns.

Measure community health through time-to-first-valid-eval, issue response time, repeat
contributors, independently maintained plugins/packs, reproducible bug reports, and
release adoption. Stars and forks are useful lagging signals, not the optimization target.

## P2 — broader capability after the contracts are trusted

- More read-only stores and framework adapters, selected by real user demand.
- Multi-turn RAG/agent trajectories, tool-use and authorization tests, and session privacy.
- Query rewriting, hybrid retrieval, metadata-filter, tenancy, and reranking ablations.
- Multilingual and multimodal corpora with language-specific judge validation.
- Broader versioned attack transformations and source-provenance/consistency defenses.
- Dataset slicing, error clustering, failure triage, and experiment comparison views.
- Optional Postgres/object storage and distributed workers only when measured workloads
  exceed the safe local SQLite runner.

## Work we should deliberately not do yet

- Do not add many database adapters before the raw-query retriever and target contracts.
- Do not run corpus mutation against a production collection or endpoint.
- Do not call an answer-only endpoint's missing contexts a retrieval failure.
- Do not publish more headline metrics before denominators, uncertainty, and provenance.
- Do not claim a defense works from attack-only results or one model/corpus.
- Do not build a public leaderboard before manifests and submission verification.
- Do not prioritize multi-tenancy or a distributed scheduler over correctness and basic
  external-target compatibility.
- Do not accept executable plugins or arbitrary import paths from untrusted API requests.

## First implementation queue

These are intentionally issue-sized and ordered by dependency:

1. **P0 / provenance:** RFC and tests for spec-relative paths plus corpus/QA content
   manifests; use the digest for index invalidation and run deduplication.
2. **P0 / schema:** add result and metric-definition versions, typed unavailable/skipped
   states, denominators, and migrations; remove report fallbacks that fabricate zero.
3. **P0 / retrieval:** rename the legacy single-hit metric and implement/test multi-qrel
   Precision/Recall/MAP/nDCG.
4. **P0 / variants:** create backend-aware ephemeral indexes; make filters and actual
   backend explicit; add live Qdrant contract coverage.
5. **P0 / comparisons:** add paired clean-versus-attacked defense utility records and
   confidence intervals.
6. **P0 / execution:** propagate supported seeds; separate suite/variant timing, judge
   timing, usage, cost, and sequential benchmark mode.
7. **P0 / judge:** create the human-labeled meta-evaluation pack and invalidate cache keys
   on complete judge configuration.
8. **P0 / safety:** publish `SECURITY.md` and trusted-local service warning; constrain
   filesystem roots and outbound targets before any hosted deployment guidance.
9. **P0 / target RFC:** define observations, capability protocols, execution modes, and
   unsupported semantics with native-pipeline compatibility tests.
10. **P0 / target extraction:** wrap the current pipeline as `ManagedRagTarget` and make
    suite orchestration capability-driven.
11. **P0 / external target:** ship trusted Python callable and generic HTTP answer/context
    adapters plus an end-to-end example.
12. **P0 / retrieval target:** ship the raw-query retriever contract and read-only Qdrant
    adapter with non-mutation tests.
13. **P1 / CI:** add policies, pinned-baseline comparison, JUnit/SARIF, and finding
    promotion.
14. **P1 / plugins:** entry-point registry, version negotiation, conformance kit, and
    adapter template.
15. **P1 / community:** contributor/governance templates, packaging split, release
    automation, docs site, and tested compatibility matrix.

Every implementation issue should link to one roadmap item and include an owner, status,
acceptance test, schema/migration impact, documentation impact, and threat-model impact.
Use `proposed`, `accepted`, `in progress`, `blocked`, and `complete`; only tests and linked
evidence move an item to `complete`.

## Ecosystem evidence behind this direction

The audit deliberately looked for reusable design lessons rather than feature-count
parity:

- [Ragas](https://docs.ragas.io/en/latest/getstarted/rag_eval/) evaluates neutral records
  of questions, responses, contexts, and references, demonstrating the value of decoupling
  evaluation from pipeline ownership.
- [DeepEval](https://deepeval.com/docs/getting-started-rag) supports end-to-end and
  component-level RAG evaluation, reinforcing separate target capability levels.
- [promptfoo's RAG guide](https://www.promptfoo.dev/docs/guides/evaluate-rag/) and
  [provider contract](https://www.promptfoo.dev/docs/providers/) show why HTTP, functions,
  executables, retrieval steps, CI gates, and portable outputs lower adoption friction.
- [Giskard's quality-assessment documentation](https://docs.giskard.ai/oss/solutions/quality-assessment)
  emphasizes turning discovered cases into regression tests; its evolving APIs are also a
  warning to label stable and experimental contracts clearly.
- [Phoenix](https://arize.com/docs/phoenix/) and
  [OpenInference](https://github.com/Arize-ai/openinference) demonstrate portable,
  OpenTelemetry-based RAG observations and evaluator traces.
- [TruLens judge alignment](https://www.trulens.org/component_guides/evaluation/llm_judge_alignment/)
  provides a useful model for validating judges against held-out human labels.
- [OpenAI Evals' build guide](https://github.com/openai/evals/blob/main/docs/build-eval.md)
  recommends checking model graders with human-labeled meta-evaluations.
- The [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/)
  documents package metadata/entry points for separately distributed plugins.
- [GitHub's community health guidance](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
  covers contributor, conduct, security, support, and issue-template foundations.

These projects are references, not specifications for Crucible. The intended
differentiator remains a controlled RAG threat laboratory: reproducible corpus mutation,
causal attack-stage evidence, paired defense trade-offs, local/private operation, and a
single view across retrieval, faithfulness, security, privacy, latency, and cost.
