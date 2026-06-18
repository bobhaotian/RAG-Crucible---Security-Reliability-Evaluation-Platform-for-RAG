# rag-crucible — developer entrypoints
# Everything goes through uv; `make setup` once, then any target.

UV ?= uv
DEMO_SPEC ?= specs/demo.yaml
FAKE_SPEC ?= specs/smoke-fake.yaml

.PHONY: setup lint format typecheck test test-local corpus ingest demo demo-fake \
        serve worker compose-up dashboard clean help

setup: ## install all deps (incl. local-model extra + dev tools)
	$(UV) sync --extra local

lint: ## ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## auto-fix lint + formatting
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## mypy --strict over crucible/ and scripts/
	$(UV) run mypy

test: ## unit + integration tests (no model downloads)
	$(UV) run pytest -q

test-local: ## also run tests that exercise real local models
	$(UV) run pytest -q -m local_models

corpus: ## regenerate the seeded corpus + QA labels (deterministic)
	$(UV) run python scripts/generate_seeded_corpus.py --out datasets/seeded --seed 13

ingest: ## build the demo index (local provider; downloads MiniLM on first run)
	$(UV) run crucible ingest $(DEMO_SPEC)

demo: ## end-to-end: ingest + sample query + full evaluation with plots (local models)
	$(UV) run crucible ingest $(DEMO_SPEC)
	$(UV) run crucible query $(DEMO_SPEC) "What is the battery life of the AT-300 inspection drone?"
	$(UV) run crucible eval $(DEMO_SPEC) --out results/demo
	@echo "" && cat results/demo/summary.md

demo-fake: ## same flow on the deterministic fake provider (instant, no downloads)
	$(UV) run crucible ingest $(FAKE_SPEC)
	$(UV) run crucible query $(FAKE_SPEC) "What is the battery life of the AT-300 inspection drone?"
	$(UV) run crucible eval $(FAKE_SPEC) --out results/smoke-fake
	@echo "" && cat results/smoke-fake/summary.md

serve: ## start the API (live /query on the demo spec + run submission)
	$(UV) run crucible serve --spec $(DEMO_SPEC)

worker: ## start the evaluation worker (claims submitted runs)
	$(UV) run crucible worker

compose-up: ## API + worker + dashboard in containers (fake provider, zero downloads)
	docker compose up --build

dashboard: ## run the dashboard dev server (proxies to the API on :8000)
	cd dashboard && npm install && npm run dev

clean: ## remove caches and run artifacts
	rm -rf artifacts .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} \;

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
