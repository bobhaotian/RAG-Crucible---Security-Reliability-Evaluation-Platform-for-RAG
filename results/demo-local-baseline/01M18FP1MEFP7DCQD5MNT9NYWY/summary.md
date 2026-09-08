# Evaluation summary — `demo-local-baseline`

- spec hash: `368b99684273` · seed: 42
- started 2026-08-30T04:43:43+00:00 · finished 2026-08-30T04:47:43+00:00

## Retrieval

| metric | rerank off | rerank on | lift |
|---|---|---|---|
| recall@1 | 0.9821 | 1.0000 | +0.0179 |
| ndcg@1 | 0.9821 | 1.0000 | +0.0179 |
| recall@5 | 1.0000 | 1.0000 | +0.0000 |
| ndcg@5 | 0.9934 | 1.0000 | +0.0066 |
| recall@10 | 1.0000 | 1.0000 | +0.0000 |
| ndcg@10 | 0.9934 | 1.0000 | +0.0066 |
| recall@20 | 1.0000 | 1.0000 | +0.0000 |
| ndcg@20 | 0.9934 | 1.0000 | +0.0066 |
| mrr | 0.9911 | 1.0000 | +0.0089 |

## Faithfulness

_20 answers judged_

| metric | value |
|---|---|
| groundedness | 0.3684 |
| hallucination_rate | 0.6842 |
| answer_accuracy | 0.8500 |
| citation_parse_rate | 0.2500 |
| citation_precision | 0.8000 |

## Security

- poison_retrieval_rate: 1.0000
- injection_retrieval_rate: 1.0000

| attack-success rate | none | prompt_isolation | injection_filter |
|---|---|---|---|
| knowledge_corruption_rate | 0.2000 | 0.4000 | 0.3000 |
| injection_compliance_rate | 0.1000 | 0.4000 | 0.0000 |

## Privacy

| condition | retrieval exposure | generation leakage |
|---|---|---|
| none | 1.0000 | 0.1852 |
| pii_filter | 1.0000 | 0.0000 |

Leakage by probe style (no redaction): direct 0.22 · indirect 0.00 · paraphrase 0.33

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 190 | 103.3 | 49.1 | 547.0 |
| generate | 134 | 3636.6 | 3355.4 | 6404.9 |
| rerank | 190 | 176.2 | 132.1 | 331.5 |
| retrieve | 190 | 0.8 | 0.2 | 1.0 |

