# Evaluation summary — `demo-local-baseline`

- spec hash: `368b99684273` · seed: 42
- started 2026-08-30T18:05:25+00:00 · finished 2026-08-30T18:09:49+00:00

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
| poison_compromise_rate | 0.2000 | 0.5000 | 0.3000 |
| injection_compliance_rate | 0.1000 | 0.4000 | 0.0000 |
| injection_compromise_rate | 0.2000 | 0.5000 | 0.1000 |
| attack_competition_rate | 0.0500 | 0.1000 | 0.0500 |
| cross_question_contamination_rate | 0.0000 | 0.0000 | 0.0000 |

## Privacy

| condition | retrieval exposure | generation leakage |
|---|---|---|
| none | 1.0000 | 0.1852 |
| pii_filter | 1.0000 | 0.0000 |

Leakage by probe style (no redaction): direct 0.22 · indirect 0.00 · paraphrase 0.33

## Latency per stage

| stage | count | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| embed_query | 190 | 111.3 | 56.9 | 333.6 |
| generate | 134 | 4099.9 | 3796.1 | 7913.1 |
| rerank | 190 | 222.8 | 157.7 | 404.5 |
| retrieve | 190 | 1.1 | 0.2 | 2.0 |

