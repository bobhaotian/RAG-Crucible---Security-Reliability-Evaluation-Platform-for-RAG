# Evaluation summary — `scifact-local`

- spec hash: `ceb0e5196bf2` · seed: 42
- started 2026-06-11T18:07:09+00:00 · finished 2026-06-11T18:08:12+00:00

## Retrieval

| metric | rerank off | rerank on | lift |
|---|---|---|---|
| recall@1 | 0.4967 | 0.5800 | +0.0833 |
| ndcg@1 | 0.4967 | 0.5800 | +0.0833 |
| recall@5 | 0.7467 | 0.7733 | +0.0266 |
| ndcg@5 | 0.6276 | 0.6816 | +0.0540 |
| recall@10 | 0.8000 | 0.8200 | +0.0200 |
| ndcg@10 | 0.6446 | 0.6968 | +0.0522 |
| recall@20 | 0.8533 | 0.8533 | +0.0000 |
| ndcg@20 | 0.6582 | 0.7054 | +0.0472 |
| mrr | 0.5989 | 0.6599 | +0.0610 |

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 300 | 30.4 | 9.7 | 33.2 |
| rerank | 300 | 179.5 | 161.8 | 246.7 |
| retrieve | 300 | 0.4 | 0.4 | 0.6 |

