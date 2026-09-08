# Evaluation summary — `smoke-fake`

- spec hash: `6321e72c3fbc` · seed: 42
- started 2026-09-04T21:19:09+00:00 · finished 2026-09-04T21:19:10+00:00

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
| citation_parse_rate | 1.0000 |
| answer_accuracy | 0.6964 |
| citation_precision | 1.0000 |

## Security

- poison_retrieval_rate: 1.0000
- injection_retrieval_rate: 1.0000

| security/control rate | none | prompt_isolation | injection_filter |
|---|---|---|---|
| knowledge_corruption_rate | 1.0000 | 1.0000 | 1.0000 |
| poison_compromise_rate | 1.0000 | 1.0000 | 1.0000 |
| injection_compliance_rate | 0.0000 | 0.0000 | 0.0000 |
| injection_compromise_rate | 0.6667 | 0.6667 | 0.8333 |
| attack_abstention_rate | 0.0000 | 0.0000 | 0.0000 |
| attack_competition_rate | 0.1667 | 0.1667 | 0.1667 |
| cross_question_contamination_rate | 0.4167 | 0.4167 | 0.7500 |
| clean_abstention_rate | 0.0000 | 0.0000 | 0.0000 |
| clean_answer_accuracy | 0.5500 | 0.5500 | 0.5500 |

## Privacy

| condition | retrieval exposure | generation leakage |
|---|---|---|
| none | 0.9630 | 0.5185 |
| pii_filter | 0.9630 | 0.0000 |

Leakage by probe style (no redaction): direct 0.67 · indirect 0.33 · paraphrase 0.56

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 262 | 0.0 | 0.0 | 0.0 |
| generate | 206 | 0.1 | 0.1 | 0.2 |
| rerank | 262 | 0.4 | 0.4 | 0.5 |
| retrieve | 262 | 0.0 | 0.0 | 0.0 |

