# Synthetic valid-time comparison

Six atomic source fixtures, eight questions, FTS mode, k=10, context budget 4000.
Both runs use identical source/corpus hashes and configured GPT-5.6 Luna for answers
(one provider call per run, two total). No private corpus, extraction call or judge.
The baseline deliberately bypasses temporal eligibility while retaining scope; it
reproduces the prior status-only selection over the same documents.

| Metric | Prior eligibility | Temporal eligibility |
|---|---:|---:|
| Queries with stale source results | 5/8 | 0/8 |
| Current recall@10 | 1.0 | 1.0 |
| Historical recall@10 | 1.0 | 1.0 |
| Correct model answers | 3/8 | 8/8 |
| Stale model answers | 1/8 | 0/8 |
| Correct expiry abstention | 0/1 | 1/1 |

All sixteen answers were inspected: baseline abstained on the four ambiguous port
queries, answered the three unambiguous facts, and incorrectly returned the expired
temporary value. The temporal run returned 8000/7000/8000/9000/enabled/empty/
temporary-test/7000 in fixture order. Empty is the expected expiry abstention.
Source IDs in ranking are retained separately; the generic context renderer prints
empty brackets for nested assertion provenance, so this run does not test citations.

Historical selection is supplied to retrieval; the answer model sees the resulting
question/context. The experiment does not test natural-language date parsing.
This tiny controlled fixture is evidence of the eligibility behavior, not a general
answer-quality or provider-comparison claim. Costs/tokens were not exposed by CLI.
The JSON temporal section describes retrieval-only metrics; model answer metrics
are separately present under summary. Temporary databases were removed and cleanup
verified by the benchmark harness.
