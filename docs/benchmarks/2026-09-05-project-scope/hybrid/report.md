# Synthetic memory benchmark

Mode: retrieval; search: hybrid; smoke: False.

Corpus SHA-256: `b55c9f7665b724e6a95d8aca255cf41ddc8c087fccd0f1ace3a887a0b7792bbe`. Revision: `7c105457ff64f8570afc7c9324949e8d2923893d`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 8 | 2 | 6 |
| answerable_queries | 6 | 2 | 4 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 0 | 0 | 0 |
| judge_scored_queries | 0 | 0 | 0 |
| recall_at_5 | 1 | 1 | 1 |
| recall_at_10 | 1 | 1 | 1 |
| mrr | 1 | 1 | 1 |
| answer_accuracy | not measured | not measured | not measured |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | not measured | not measured | not measured |
| stale_answer_rate | not measured | not measured | not measured |
| context_chars_mean | 157 | 160 | 156 |
| latency_ms_p50 | 175.5 | 176.3 | 162.6 |
| latency_ms_p95 | 347.7 | 189.7 | 347.7 |

Indexing: 4/4 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. No quality tuning was performed on held-out results.
