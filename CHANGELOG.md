# Changelog

- **Phase 2 — measurement:** retrieval suite (recall@k/nDCG@k/MRR) with explicit rerank-lift variants, faithfulness suite (sentence-claim entailment via swappable LLM/heuristic judge with committed judgment cache, citation correctness, answer accuracy), `crucible eval` + reports (results.json, summary.md, plots), BEIR SciFact fetch script, measured results in README.
- **Phase 1 — core spine:** provider interface with `local` + `fake` implementations, ingestion (loaders/filters/chunkers), FAISS index, RAG pipeline with citations and per-stage timing, `crucible` CLI, seeded corpus + QA labels, tests + CI.
- **Phase 0 — design:** `docs/DESIGN.md` and `docs/architecture.md` written; MVP cut line confirmed after Phase 3.
