# rag-crucible — developer entrypoints
# Everything goes through uv; `make setup` once, then any target.

UV ?= uv
DEMO_SPEC ?= specs/demo.yaml
FAKE_SPEC ?= specs/smoke-fake.yaml

.PHONY: setup lint format typecheck test test-local corpus ingest demo demo-fake clean help

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

demo: ## end-to-end: ingest + answer sample queries with the local provider
	$(UV) run crucible ingest $(DEMO_SPEC)
	$(UV) run crucible query $(DEMO_SPEC) "What is the battery life of the AT-300 inspection drone?"
	$(UV) run crucible query $(DEMO_SPEC) "How many days of paid vacation do employees get?"
	$(UV) run crucible query $(DEMO_SPEC) "What does error code E-114 mean on the SR-2 rover?"

demo-fake: ## same demo on the deterministic fake provider (instant, no downloads)
	$(UV) run crucible ingest $(FAKE_SPEC)
	$(UV) run crucible query $(FAKE_SPEC) "What is the battery life of the AT-300 inspection drone?"

clean: ## remove caches and run artifacts
	rm -rf artifacts .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} \;

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
