# Change Proposal: Selective local neural reranking

Stable work ID: 5.3; Issue #28. Authorized sequential implementation.
Source: merged feature 5.2, `342bccf6fce51213b7bac1560e41e7554b2e989c`.

## Outcome and acceptance

Use the existing validated ordering callback for a trained multilingual local
query/passage model. Automatically consider ambiguous ordinary auto searches;
retain exact identity/symbol, lexical, explicit hybrid and baseline behavior.
Bound candidate count, input size, concurrent work and total inference time.
Reorder only eligible original hits; preserve all payloads, evidence and citations.
No hosted inference, model downloads during search, new Python dependencies,
schema migration, persisted rerank cache, or application-owned model daemon.
Publish three practical paired Trading examples with numerical limits and model
revision, resources and cold/warm measurements; complete independent review,
full suites and populated multi-user/domain coexistence and rollback checks.

## Compatibility and operations

The model runtime is an optional operator-managed loopback llama.cpp endpoint;
agentic-rag already supports independent local inference and a validated ranker
seam. This change supplies the bounded adapter, not a new service manager.
Installations without the endpoint retain previous ordering. Existing TOML and
CLI/MCP call shapes remain valid; add optional rerank=off for comparison/recovery.
No existing configuration is edited. Adoption and model-service rollout require
separate authorization; dependency alerts remain tracked in #37.

Operational artifact: docs/local-reranker.md, owner maintainer, due before PR,
with pinned download/checksum, loopback/offline launch, synthetic smoke test,
coexistence, restart/adoption and rollback; rehearse in isolated local lab only.
No critical database operation is introduced; no database recovery playbook delta.
