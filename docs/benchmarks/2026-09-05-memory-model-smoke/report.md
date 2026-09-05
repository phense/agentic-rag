# Synthetic memory benchmark

Mode: end-to-end; search: hybrid; smoke: True.

Corpus SHA-256: `588d7db06b4b161f88c76d5b0f8d359d268573b47490efda423dda9285c1cd45`. Revision: `d121ab86c57cc24429aab5c774700aad4b40f248`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 8 | 3 | 5 |
| answerable_queries | 6 | 2 | 4 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 8 | 3 | 5 |
| judge_scored_queries | 8 | 3 | 5 |
| recall_at_5 | 1 | 1 | 1 |
| recall_at_10 | 1 | 1 | 1 |
| mrr | 1 | 1 | 1 |
| answer_accuracy | 1 | 1 | 1 |
| judge_accuracy | 1 | 1 | 1 |
| unanswerable_accuracy | 1 | 1 | 1 |
| stale_answer_rate | 0 | 0 | 0 |
| context_chars_mean | 1679 | 1657 | 1692 |
| latency_ms_p50 | 165.3 | 165.3 | 166.1 |
| latency_ms_p95 | 178.8 | 178.8 | 171.8 |

Indexing: 10/10 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. No quality tuning was performed on held-out results.
