# Synthetic memory benchmark

Mode: retrieval; search: fts; smoke: False.

Corpus SHA-256: `a74d5eda177181eabe1cfb0a9178252e7010e6e60d64f6f850a4c6a3c4a6b805`. Revision: `f592dd6667d56a05387281e207d63b7062d378b1`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 8 | not measured | 8 |
| answerable_queries | 7 | not measured | 7 |
| failed_queries | 0 | not measured | 0 |
| answer_scored_queries | 8 | not measured | 8 |
| judge_scored_queries | 0 | not measured | 0 |
| recall_at_5 | 1 | not measured | 1 |
| recall_at_10 | 1 | not measured | 1 |
| mrr | 1 | not measured | 1 |
| answer_accuracy | 1 | not measured | 1 |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | 1 | not measured | 1 |
| stale_answer_rate | 0 | not measured | 0 |
| context_chars_mean | 35 | not measured | 35 |
| latency_ms_p50 | 12.5 | not measured | 12.5 |
| latency_ms_p95 | 13.9 | not measured | 13.9 |

Indexing: 6/6 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. No quality tuning was performed on held-out results.
