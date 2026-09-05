# Synthetic memory benchmark

Mode: retrieval; search: fts; smoke: False.

Corpus SHA-256: `67b428341475ebc36d9969e417dfa98583b7f32b6c467d993ed9a7c51eacac97`. Revision: `126a2b3883bab1d186c73615a26847fa0e890109`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 10 | 4 | 6 |
| answerable_queries | 6 | 2 | 4 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 0 | 0 | 0 |
| judge_scored_queries | 0 | 0 | 0 |
| recall_at_5 | 0.5833 | 0.5 | 0.625 |
| recall_at_10 | 0.5833 | 0.5 | 0.625 |
| mrr | 0.6667 | 0.5 | 0.75 |
| answer_accuracy | not measured | not measured | not measured |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | not measured | not measured | not measured |
| stale_answer_rate | not measured | not measured | not measured |
| context_chars_mean | 146.5 | 108.8 | 171.7 |
| latency_ms_p50 | 12.07 | 16.43 | 11.91 |
| latency_ms_p95 | 21.32 | 16.98 | 21.32 |
| evidence_recall | 0.5 | 0.5 | 0.5 |
| false_positive_rate | 0 | 0 | 0 |

Indexing: 9/9 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. Development and test labels are recorded; independence and tuning history must be documented with each corpus.
