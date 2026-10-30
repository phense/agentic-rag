# Tasks: Providers and recoverable embedding indexes

## Stable work ID

RAG-061, [spec.md](spec.md), [plan.md](plan.md).

## Architecture findings

AF061-001: all managed semantic consumers share one identity (coordinator).
AF061-002: source/cutover concurrency (index implementation).
AF061-003: scoped/owner authority (index implementation + coordinator).
AF061-004: honest provider/secret/egress contract (provider implementation).

## Tests

Test-first provider MockTransport/config/probe bounds; real PostgreSQL generation,
scope, concurrent edit/cutover and rollback tests; existing extraction/cache/search
regressions; populated upgrade/strict restore/hash verification; three synthetic
measurement cases; independent full bounded review and final full-suite exit.

## Implementation slices

### Slice S1: Verified provider profiles

- [x] T001 [IC001/002] Freeze provider API and ownership in plan; inspect existing auth contracts before edits.
- [x] T002 [US001/003] [AF061-004] Write and observe failing profile/identity/secret/error/bounds tests — tests/test_providers.py; depends on T001.
- [x] T003 [AC001–003/007] Implement immutable profiles, protected refs, bounded adapters and independent extraction dispatch — config.py, providers.py, embed.py, llm.py; depends on T002.
- [x] T004 Verify provider suite plus existing config/embed/LLM/cache tests; record stable API before S2 — evidence in agent report; depends on T003.

### Slice S2: Resumable generation lifecycle

- [x] T005 [US002] [AF061-002/003] Test-first additive SQL027, scope-checked gateway, source-bound generations, bounded resume, atomic activation and catch-up rollback — indexes.py, sql/027_provider_indexes.sql, tests/test_provider_indexes.py; depends on T004.
- [x] T006 [AF061-001] Route managed search/mining through the selected generation and suppress legacy vector mixing; CLI explicit inspect/probe/create/build/status/activate/rollback, store gateway facade — search.py, mining.py, store.py, cli.py, provider_cli.py; depends on T005.
- [x] T007 [AC004–008] Verify incompatible/equal dimensions, alias drift, interruption, concurrent writes, RLS and rollback with post-cutover writes; review slice — tests/test_provider_indexes.py and integration tests; depends on T005/T006.

### Slice S3: Existing-install proof and operator delivery

- [x] T008 [AC008] Rehearse populated026→027 upgrade and strict restore with original rows/ACLs/IDs/queues intact, local and central modes; verify old-client compatibility — tests and isolated rehearsal script; depends on T007.
- [x] T009 [AC009] Record three reproducible synthetic cold/warm/resource/request cases, exact revisions and limits — scripts/measure_provider_indexes.py, docs/verification/issue61-providers.md; depends on T007.
- [x] T010 [PB061-OPS] Author/review/rehearse docs/provider-indexes.md; confirm reused PB061-DEV before upgrade rehearsal; update README/handbook and four release metadata files to0.6.14; depends on T007.

### Slice S4: Reconcile and verify integrated behavior

- [x] T011 Reconcile docs/uml/provider-indexes.md and findings against actual code; independent strong architect derives real success and recovery tests, run both; depends on T008–T010.
- [x] T012 Independent complete bounded diff review; fix/review all C/H/M, add Low findings to#75; depends on T011.

### Slice S5: Convergence and final verification handoff

- [x] T013 Invoke speckit-converge; reconcile acceptance, architecture, actual exits and review state, execute any appended fix slice; full suite, version/docs checks; depends on T012.
- [x] T014 Commit/push, create/link PR immediately, report step3/15 and wait for maintainer merge/weiter; depends on T013.

## Dependencies and ownership

S1 → S2 → S3 → S4 → S5. No parallel producer/consumer implementation. Provider
worker owns config/providers/embed/llm and provider tests. Index worker owns
indexes/SQL027/index tests. Coordinator owns integration, CLI, docs and release.
All writers share one isolated feature worktree and must preserve others' edits.
Readonly reviews may overlap unrelated execution; test clusters must not overlap.

## Playbook obligations

PB061-OPS readiness blocks T014; independent content review plus actual synthetic
CLI resume/cutover/rollback evidence required. Reused PB061-DEV applicability must
be checked before T008; no production upgrade is part of this execution.

## Publication handoff

[PR #81](https://github.com/phense/agentic-rag/pull/81) is published and linked.
Implementation and verification are complete; maintainer merge/weiter is pending.
Roadmap#58 step3/15; continue with#62 only after approval.
