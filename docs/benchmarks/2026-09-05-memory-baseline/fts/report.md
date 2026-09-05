# Synthetic memory benchmark

Mode: retrieval; search: fts; smoke: False.

Corpus SHA-256: `f5d819a54fe6e6d48d4eddf3d7e2f7827a43c003381a8a30d5e05e0ba6126642`. Revision: `0e6e364e17ba1a660514a1c2944fa51573ea6e1e`.

Synthetic data only. Scores are a baseline for this corpus, not evidence of real-workload superiority.

| Metric | Overall | Development | Held out |
|---|---:|---:|---:|
| queries | 60 | 18 | 42 |
| answerable_queries | 48 | 14 | 34 |
| failed_queries | 0 | 0 | 0 |
| answer_scored_queries | 0 | 0 | 0 |
| judge_scored_queries | 0 | 0 | 0 |
| recall_at_5 | 0.1875 | 0.1429 | 0.2059 |
| recall_at_10 | 0.1875 | 0.1429 | 0.2059 |
| mrr | 0.1875 | 0.1429 | 0.2059 |
| answer_accuracy | not measured | not measured | not measured |
| judge_accuracy | not measured | not measured | not measured |
| unanswerable_accuracy | not measured | not measured | not measured |
| stale_answer_rate | not measured | not measured | not measured |
| context_chars_mean | 25.25 | 25.83 | 25 |
| latency_ms_p50 | 6.86 | 7.097 | 6.645 |
| latency_ms_p95 | 8.897 | 50.78 | 8.173 |

Indexing: 26/26 sources; cleanup: verified.

Retrieval recall uses all answerable queries, including ingestion/query failures. Unanswerable cases are scored separately. Duplicate returned chunks consume rank positions.

Recall measures source identity, not whether the needed fact survives snippet/context clipping. A long source can count as retrieved while its answer is absent; use the separate answer stage to measure this gap.

`answer_accuracy` is deterministic alias matching and can disagree with semantic correctness; `judge_accuracy` is separately model-judged and requires spot checks. Bootstrap intervals and category breakdowns are in results.json.

Context characters are exact; token counts are estimates. Provider billing and token usage are unknown, not zero. No quality tuning was performed on held-out results.
