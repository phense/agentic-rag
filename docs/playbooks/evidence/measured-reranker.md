---
title: PB062-OPS review and rehearsal evidence
type: reference
audience: administrators
version: 0.6.15
---

# PB062-OPS review and rehearsal evidence

## Scope

- Playbook: [local-reranker.md](../../local-reranker.md), target 0.6.15/schema027.
- Requirement: Issue #62, C062-003–007; operator/coordinator owner, before delivery.
- Required level: independent content review and owned synthetic local/central
  rollback plus combined 4 CPU / 8 GiB native-model rehearsal. Production is excluded.
- Writing scale: medium standalone update; documentation-authoring,
  human-prose-drafting, writing-procedures and terminology-guard.

## Content review

Independent content and measurement reviews passed. Inspection covered executable
options, offline inspection, loopback/source boundaries, decisions, failure paths,
interruption/rollback, locations, glossary and prose constraints. The reviewer
checked the pinned tiny-model adoption instructions and the actual old-engine
local/central recovery evidence. The completed full-suite result is linked below.

## Rehearsal

Populated synthetic local and authenticated HTTP compatibility, exact-identifier
bypass, foreign-project exclusion, source withdrawal, actual archived0.6.14engine
rollback and canonical-table hash preservation pass in
`tests/service/test_rerank_compat.py`. The current focused run passed 28 tests in
11.66 s, one upstream Starlette warning. Additional measurement regressions follow.
Actual native-model resource rehearsal passed at 4ac82cd: 70/70 sources, 327 search observations,
zero query/trial/citation errors, canonical rows unchanged; effective 4 CPU / 8 GiB zero-swap
combined unit, exit 0 and external inactive/absent-cgroup proof. Supplemental three
fresh model starts per model also passed independently of selection. See
[raw measurements](../../benchmarks/2026-10-30-measured-reranker/README.md).
The final complete suite passed: 1735 passed, 1 skipped, 1 warning in 1565.23s (0:26:05). See the
[actual output and source manifest](../../verification/issue62-reranker.md).

## Acceptance and freshness

Content reviewed; resource/local/central recovery rehearsals and the actual
complete suite passed. Final source/link/render and independent artifact checks
also passed; see the [acceptance review](../../verification/issue62/reviews/final-delivery-review.txt). No production deployment, runtime replacement or private
source inference has been authorized by this evidence.
