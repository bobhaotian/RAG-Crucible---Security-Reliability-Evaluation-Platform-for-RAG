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

The run removed the provenance label but not a second one: each attack document's
source path still named it (`__poison__/q001.md`), and the prompt prints that path
beside every chunk, so the generator could see which passage was the attack. Hiding
only the canary path moved privacy leakage under no defense from 5/27 to 10/27 in one
run on Qwen2.5-0.5B (all five changed probes went one way; exact McNemar *p* = 0.0625,
not significant), so the model does read the path. Its effect on the table above is
not established. Planted documents now get corpus-shaped paths (see `CHANGELOG.md`). That measurement replaced the path with a neutral hex name in `kb/`; the corpus-shaped scheme now shipped has not itself been measured on a real model.,
and the numbers above are left as recorded.

The full generated JSON remains a local run artifact rather than another
committed canonical result. The numbers above were measured on code at or before commit
`477ef0c`. Attack-target sampling changed after it (see `CHANGELOG.md`, A7), so newer code
attacks different targets. At that commit the executable is `crucible`, so run the commands
below with `crucible` in place of `rag-crucible`. On current code they run, but on a
different sample.

```console
uv run rag-crucible ingest specs/integrity-local.yaml
uv run rag-crucible eval specs/integrity-local.yaml --out results/integrity-local
```
