---
title: PB062-OPS review and rehearsal evidence
type: reference
audience: administrators
version: 0.6.15
---

# PB062-OPS review and rehearsal evidence

## Scope

- Playbook: [local-reranker.md](../../local-reranker.md), target0.6.15/schema027.
- Requirement: Issue62, C062-003–007; operator/coordinator owner, before delivery.
- Required level: independent content review and owned synthetic local/central
  rollback plus combined4CPU8GiB native-model rehearsal. Production is excluded.
- Writing scale: medium standalone update; documentation-authoring,
  human-prose-drafting, writing-procedures and terminology-guard.

## Content review

Pending independent final review. Coordinator self-check has inspected executable
options, offline inspection, loopback/source boundaries, decisions, failure paths,
interruption/rollback, locations, glossary and prose constraints. Actual command
replay and final artifact hash are pending.

## Rehearsal

Populated synthetic local and authenticated HTTP compatibility, exact-identifier
bypass, foreign-project exclusion, source withdrawal, actual archived0.6.14engine
rollback and canonical-table hash preservation pass in
`tests/service/test_rerank_compat.py`. The current focused run passed28tests in
11.66s, one upstream Starlette warning. Additional measurement regressions follow.
Actual native-model resource rehearsal and final complete-suite results are pending.

## Acceptance and freshness

Drafted; delivery blocked until independent review and actual resource/suite
artifacts are recorded. No production deployment, runtime replacement or private
source inference has been authorized by this evidence.
