# Evaluation summary — `demo-local-disjoint`

- spec hash: `8b830dd3eb42` · seed: 42
- started 2026-08-31T18:18:24+00:00 · finished 2026-08-31T18:20:52+00:00

## Security

- poison_retrieval_rate: 1.0000
- injection_retrieval_rate: 1.0000

| attack-success rate | none | prompt_isolation | injection_filter |
|---|---|---|---|
| knowledge_corruption_rate | 0.2000 | 0.4000 | 0.3000 |
| poison_compromise_rate | 0.2000 | 0.4000 | 0.3000 |
| injection_compliance_rate | 0.2000 | 0.4000 | 0.0000 |
| injection_compromise_rate | 0.2000 | 0.4000 | 0.0000 |
| attack_competition_rate | 0.0000 | 0.0000 | 0.0000 |
| cross_question_contamination_rate | 0.0000 | 0.0000 | 0.0000 |

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 60 | 73.7 | 46.0 | 205.6 |
| generate | 60 | 2070.2 | 2011.1 | 3352.6 |
| rerank | 60 | 140.6 | 126.0 | 223.1 |
| retrieve | 60 | 0.4 | 0.2 | 0.7 |

