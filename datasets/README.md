# Datasets

## `seeded/` (committed)

A small synthetic knowledge base for a fictional company ("Helios Robotics"):
~35 documents across `.md` / `.txt` / `.html` / `.pdf`, plus `qa.jsonl` with 56
labeled questions. Regenerate deterministically with:

```sh
make corpus   # python scripts/generate_seeded_corpus.py --out datasets/seeded --seed 13
```

Properties that the rest of the platform relies on:

- **Gold labels are substrings.** Each QA pair's `gold_fact` is a sentence that
  appears verbatim on a single line of exactly one document. Gold *chunks* are
  derived at eval time as "chunks containing the fact", so labels survive any
  chunking configuration.
- **Noise documents are deliberate.** `noise/` contains an exact duplicate, a
  French document, and a boilerplate-only page — one per ingest filter, so
  filter behavior is observable in the demo output.
- **PDFs carry no gold facts** (extraction reflows lines); they exercise the
  loader path.
- **All content is fictional.** No real personal data anywhere; privacy
  canaries are seeded at eval time by the privacy suite (Phase 5), never
  committed.

## `scifact/` (fetched on demand, never committed)

BEIR SciFact: ~5.2k scientific abstracts + 300 test queries with
document-level gold labels — the public retrieval benchmark. Fetch + convert
(~3 MB download), then evaluate:

```sh
uv run python scripts/fetch_scifact.py
uv run crucible ingest specs/scifact-local.yaml
uv run crucible eval specs/scifact-local.yaml
```

Gold labels use the `gold_docs` kind (document ids) rather than fact
substrings; only the retrieval suite applies since SciFact has no short
answer strings.
