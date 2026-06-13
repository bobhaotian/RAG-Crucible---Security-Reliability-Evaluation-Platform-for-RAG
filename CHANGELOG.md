# Changelog

- **Phase 3 — service (MVP complete):** SQLite result store doubling as job queue (atomic claims, spec-hash dedupe), evaluation worker with suite-level failure isolation, FastAPI API (submit/poll/results/records/cancel + live /query + health), provider warm-up before timing, bounded item concurrency in suites, `crucible submit|worker|serve|runs`, Dockerfile + docker-compose (api + worker), CI image build.
- **Phase 2 — measurement:** retrieval suite (recall@k/nDCG@k/MRR) with explicit rerank-lift variants, faithfulness suite (sentence-claim entailment via swappable LLM/heuristic judge with committed judgment cache, citation correctness, answer accuracy), `crucible eval` + reports (results.json, summary.md, plots), BEIR SciFact fetch script, measured results in README.
- **Phase 1 — core spine:** provider interface with `local` + `fake` implementations, ingestion (loaders/filters/chunkers), FAISS index, RAG pipeline with citations and per-stage timing, `crucible` CLI, seeded corpus + QA labels, tests + CI.
- **Phase 0 — design:** `docs/DESIGN.md` and `docs/architecture.md` written; MVP cut line confirmed after Phase 3.
