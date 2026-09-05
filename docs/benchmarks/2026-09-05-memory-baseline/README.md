# Initial synthetic memory retrieval baseline

Measured from committed implementation `0e6e364` using the installed local CLI.
Both runs use the same 26-source, 60-question EN/DE corpus and 4,000-character
maximum context. All 26 sources indexed; no operational failures. Twelve questions
are explicitly unanswerable and excluded only from evidence recall, not dropped.
No retrieval parameters were tuned after observing held-out results.

| Metric | FTS fallback | Hybrid (local bge-m3) |
|---|---:|---:|
| answerable_queries | 48 | 48 |
| recall_at_5 | 0.1875 | 1 |
| recall_at_10 | 0.1875 | 1 |
| mrr | 0.1875 | 0.9896 |
| latency_ms_p50 | 6.86 | 165.8 |
| latency_ms_p95 | 8.897 | 172.2 |
| context_chars_mean | 25.25 | 1765 |

See [FTS report](fts/report.md), [hybrid report](hybrid/report.md) and
[comparison JSON](comparison.json). Each run retains the exact corpus, raw per-query
rankings, evidence snippets, bounded contexts, category/split metrics, bootstrap
intervals and source hashes in its results.json.

This corpus has a retrieval ceiling: hybrid source recall is already perfect here.
That establishes a reproducible smoke baseline, not real-world perfection or an
answer-quality claim. In particular, source IDs can be found while long-tail facts
are clipped out of returned snippets. Richer held-out workloads will be needed to
rank subsequent quality changes once this initial corpus saturates.

Real extraction, answer correctness, abstention and stale-answer/model-judge
quality were **not measured**. No paid provider call occurred; the configured
structured CLI does not expose billing telemetry. The actual mining pipeline is
covered by integration tests with a deterministic model boundary. Run and manually
spot-check the optional model stages only with an authorized evaluation budget.

Both owned databases were cleaned up. Runs use no canonical-store documents,
private transcripts, new providers or changed production retrieval ranking.
For commands, definitions and comparison constraints see [the benchmark guide](../memory-quality.md).
