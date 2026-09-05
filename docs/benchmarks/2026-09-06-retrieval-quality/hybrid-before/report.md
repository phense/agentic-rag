# Synthetic memory benchmark

Mode: retrieval; search: hybrid; smoke: False.

Corpus SHA-256: `67b428341475ebc36d9969e417dfa98583b7f32b6c467d993ed9a7c51eacac97`. Revision: `126a2b3883bab1d186c73615a26847fa0e890109`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 10 | 4 | 6 |
| answerable_queries | 6 | 2 | 4 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 0 | 0 | 0 |
| judge_scored_queries | 0 | 0 | 0 |
| recall_at_5 | 0.8333 | 1 | 0.75 |
| recall_at_10 | 0.8333 | 1 | 0.75 |
| mrr | 1 | 1 | 1 |
| answer_accuracy | not measured | not measured | not measured |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | not measured | not measured | not measured |
| stale_answer_rate | not measured | not measured | not measured |
| context_chars_mean | 3983 | 3991 | 3977 |
| latency_ms_p50 | 204.2 | 201 | 204.4 |
| latency_ms_p95 | 371.1 | 214.7 | 371.1 |
| evidence_recall | 0.3333 | 0.5 | 0.25 |
| false_positive_rate | 1 | 1 | 1 |

Indexing: 9/9 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. Development and test labels are recorded; independence and tuning history must be documented with each corpus.
