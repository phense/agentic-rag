# Change Tasks: Measured local reranker configurations

## Stable work ID

RAG-062 / `measured-reranker`, Issue#62, step4/15.
See [proposal](proposal.md), [design](design.md) and
[delta](specs/retrieval-ordering/spec.md).

## Tests and implementation

- [x] C062-001 Observe meaningful RED tests for configuration/model/policy bounds,
  fixed safe diagnostics and default compatibility; implement minimal ordering
  changes in config.py/neural_rerank.py/search.py; existing neural tests GREEN.
- [x] C062-002 Author versioned EN/DE synthetic failure-derived corpus and RED
  family/split/duplicate/metric/seal tests; implement bounded evaluation module
  and script using audited owned databases. Depends on001.
- [x] C062-003 Verify populated local/central existing-client ordering, exact/time/
  scope/source-withdrawal parity and code/config rollback. Depends on001.
- [x] C062-004 Freeze source and candidates; run checksum-verified isolated real
  local model evaluation, publish all failures/metrics/resources and2–3 examples.
  Distinguish actual host from reference-class capacity. Depends on002/003.
- [x] C062-005 PB062-OPS author/content-review/synthetic-rehearsal; update relevant
  docs/FEATURES and four release metadata references to0.6.15. Depends on004.
- [x] C062-006 Independent complete bounded diff review; verify/fix/re-review
  every C/H/M, retain Low findings in#75. Depends on001–005.

## Completion evidence

- [x] C062-007 Actual complete suite, current source hashes, release/links/render
  checks and fresh verification; no deferred specified behavior. Depends on006.
- [x] C062-008 Prepare the verified delivery manifest, PR description and
  maintainer handoff. Depends on007. Requirement synchronization, archival and PR
  publication are terminal delivery steps after all implementation gates pass.

## Dependencies and ownership

One coordinator owns runtime, corpus, evaluation and docs. Independent reviewers
own only their ignored reports and must not implement reviewed product files.
No concurrent mutable database tests on one cluster. Required PB062-OPS review
and rehearsal block delivery. No production rollout is part of any task.
