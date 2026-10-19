# dashboard

A read-only Vite + React + TypeScript SPA over the rag-crucible API. It renders a
run's quality–robustness–privacy trade-off, rerank lift, attack success
with/without defenses, canary-leakage decomposition, and per-stage latency, and
diffs any two runs (e.g. Cohere vs local provider, rerank on vs off).

## Dev

```sh
# 1. start the API + a worker, and submit a run so there's something to show
rag-crucible serve --spec specs/demo.yaml      # terminal 1
rag-crucible worker                            # terminal 2
rag-crucible submit specs/demo.yaml            # enqueue a run

# 2. run the dashboard (proxies /runs and /health to the API on :8000)
cd dashboard && npm install && npm run dev
```

## Build / container

```sh
npm run build          # type-check + bundle to dist/
npm test               # selector tests on Node's built-in runner (no extra dependency)
docker compose up dashboard   # nginx serving the build, proxying to the api service
```

A metric that was not measured arrives with `value: null`, a `state` and a `reason`.
Every selector in `src/metrics.ts` keeps it apart from a measured zero and from a metric
the run did not emit: it is never drawn as 0, never inverted to 1, and never feeds a
delta. `npm test` checks those rules.

Charts use Recharts; every chart returns null when its suite is absent, so
partial runs still render. The dashboard holds no evaluation logic — it only
reads the API's flat metric list (`rag_crucible/eval/types.py` → `metrics` table).
