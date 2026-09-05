# Project scope baseline

Measured from committed implementation 7c10545 using real audited gateway writes
and SQL retrieval in owned disposable databases. Four synthetic documents (A, B,
explicit global, unknown); eight labeled scope selections in English/German.
Both FTS fallback and local bge-m3 hybrid achieve Recall@5/10 and MRR 1.0 on six
answerable selections. Two negative selections are labeled separately.

Every retrieved source in every scoped query was independently checked against
its permitted scope: **zero foreign/unknown-scope violations in either run**.
Deliberate all-scope retrieval remains available. Scope and domain are distinct.
Hashes and aggregate metrics were replay-verified; no provider model command was
attempted. Context budgets are identical (4,000 characters). These fixtures test
isolation, not general relevance or answer quality.

The full tests additionally cover >50 foreign candidates in FTS and vector search,
reader roles, graph bridges, worktree/nested-path pins, concurrent scope repairs,
and rollback/idempotence. The small benchmark alone does not establish these guarantees.

See [FTS](fts/report.md), [hybrid](hybrid/report.md), [comparison](comparison.json),
and [scope policy](../../project-scope.md). Exact corpus/raw results are retained
with each run for reproducibility. Scoped E2E mining overrides are rejected
explicitly before DB/provider work; unscoped E2E remains supported.
