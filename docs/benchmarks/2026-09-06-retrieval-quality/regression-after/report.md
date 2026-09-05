# Synthetic memory benchmark

Mode: retrieval; search: hybrid; smoke: False.

Corpus SHA-256: `f5d819a54fe6e6d48d4eddf3d7e2f7827a43c003381a8a30d5e05e0ba6126642`. Revision: `126a2b3883bab1d186c73615a26847fa0e890109`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 60 | 18 | 42 |
| answerable_queries | 48 | 14 | 34 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 0 | 0 | 0 |
| judge_scored_queries | 0 | 0 | 0 |
| recall_at_5 | 1 | 1 | 1 |
| recall_at_10 | 1 | 1 | 1 |
| mrr | 0.9896 | 1 | 0.9853 |
| answer_accuracy | not measured | not measured | not measured |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | not measured | not measured | not measured |
| stale_answer_rate | not measured | not measured | not measured |
| context_chars_mean | 1765 | 1778 | 1760 |
| latency_ms_p50 | 194.2 | 195.2 | 192.7 |
| latency_ms_p95 | 202.4 | 216.6 | 202.2 |
| evidence_recall | not measured | not measured | not measured |
| false_positive_rate | 1 | 1 | 1 |

Indexing: 26/26 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. Development and test labels are recorded; independence and tuning history must be documented with each corpus.
