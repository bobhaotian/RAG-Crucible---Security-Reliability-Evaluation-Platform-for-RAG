# Evaluation summary — `integrity-smoke`

- spec hash: `5caefa0787aa` · seed: 42
- started 2026-08-30T23:22:15+00:00 · finished 2026-08-30T23:22:16+00:00

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

## Security

- poison_retrieval_rate: 0.6667
- injection_retrieval_rate: 0.7222

| attack-success rate | none | prompt_isolation | injection_filter | answer_integrity |
|---|---|---|---|---|
| knowledge_corruption_rate | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| injection_compliance_rate | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## Privacy

| condition | retrieval exposure | generation leakage |
|---|---|---|
| none | 0.9630 | 0.5185 |
| pii_filter | 0.9630 | 0.0000 |

Leakage by probe style (no redaction): direct 0.67 · indirect 0.33 · paraphrase 0.56

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 214 | 0.0 | 0.0 | 0.0 |
| generate | 158 | 0.1 | 0.1 | 0.2 |
| rerank | 214 | 0.3 | 0.3 | 0.4 |
| retrieve | 214 | 0.0 | 0.0 | 0.0 |
