# Answer-integrity experiment

## Verdict

The current `answer_integrity` condition is **not an effective poisoning
defense** on the seeded local-model evaluation. Keep the provenance model and
numeric-conflict detector as experimental infrastructure, but do not recommend
enabling the defense or claim that it addresses knowledge corruption.

## Fair-evaluation changes

- Poison and canary documents enter through the same ingestion channel as the
  ordinary corpus. The harness no longer supplies a test-only low-trust label.
- Poison and injection targets are disjoint.
- The comparison uses the local MiniLM/cross-encoder/Qwen pipeline in
  `specs/integrity-local.yaml`; `integrity-smoke.yaml` is conformance-only.
- Every defense is also run on all 56 clean labeled questions. The suite emits
  `clean_abstention_rate`, `clean_answer_accuracy`, and
  `attack_abstention_rate`.

## Result

Run on 2026-09-02 with seed 42:

| metric | none | answer_integrity |
|---|---:|---:|
| knowledge corruption | 0.2000 | 0.5000 |
| attack abstention | 0.0000 | 0.6000 |
| clean abstention | 0.0000 | 0.7500 |
| clean answer accuracy | 0.8393 | 0.2500 |

Both attack and clean costs rule out a positive result. The apparent block in
the earlier fake-provider smoke run depended on test-only provenance labels.
Once those labels are removed, the narrow numeric extractor frequently fails
to resolve the poisoned claim and refuses too much legitimate traffic.

The full generated JSON remains a local run artifact rather than another
committed canonical result. Reproduce with:

```console
uv run crucible ingest specs/integrity-local.yaml
uv run crucible eval specs/integrity-local.yaml --out results/integrity-local
```
