# Evaluation summary — `smoke-fake`

- spec hash: `8e507c8cbdf2` · seed: 42
- started 2026-06-11T18:06:10+00:00 · finished 2026-06-11T18:06:10+00:00

## Retrieval

| metric | rerank off | rerank on | lift |
|---|---|---|---|
| recall@1 | 0.8393 | 0.7500 | -0.0893 |
| ndcg@1 | 0.8393 | 0.7500 | -0.0893 |
| recall@5 | 0.9464 | 0.8393 | -0.1071 |
| ndcg@5 | 0.9069 | 0.7917 | -0.1152 |
| recall@10 | 0.9643 | 0.9821 | +0.0178 |
| ndcg@10 | 0.9132 | 0.8390 | -0.0742 |
| recall@20 | 0.9821 | 0.9821 | +0.0000 |
| ndcg@20 | 0.9173 | 0.8390 | -0.0783 |
| mrr | 0.8967 | 0.7967 | -0.1000 |

## Faithfulness

_56 answers judged_

| metric | value |
|---|---|
| groundedness | 1.0000 |
| hallucination_rate | 0.0000 |
| answer_accuracy | 0.6964 |
| citation_parse_rate | 1.0000 |
| citation_precision | 1.0000 |

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 112 | 0.0 | 0.0 | 0.0 |
| generate | 56 | 0.2 | 0.2 | 0.3 |
| rerank | 112 | 0.4 | 0.4 | 0.5 |
| retrieve | 112 | 0.0 | 0.0 | 0.1 |

