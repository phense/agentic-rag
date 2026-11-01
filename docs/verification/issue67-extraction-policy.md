---
id: V-067
title: Extraction policy verification
type: reference
doc_id: standalone
readers: [maintainer]
status: draft
version: 0.6.20 (schema032)
depends_on: [../extraction-policy.md]
assets: []
last_reviewed: 2026-11-01
summary: S1 implementation evidence for Issue67 - frozen EN/DE fixtures, mock-provider measurement, populated 0.6.19 upgrade and recovery, PB-067-OPS rehearsal, requirement dispositions, deviations and limits. Independent review, root full suite and production rollout are pending.
---

# Extraction policy verification

## Overview

[Issue67](https://github.com/phense/agentic-rag/issues/67) adds a versioned,
file-configured extraction policy for session mining. Source is
0.6.19/schema031 (`01bc13b`); the target is 0.6.20 with additive migration032.
This record covers the implementation slice S1 (T067-001..007) on branch
`feat/extraction-instructions-67`, base `11e5dc0`. Independent review (S2),
the root full suite and convergence (S3) have not run yet.

## Commits

| Commit | Task | Content |
|---|---|---|
| `ad256e7` | T067-001 | Frozen EN/DE fixtures, policies and labels with checksums, before product code |
| `a8b63ec` | T067-002 | `extraction_policy.py` strict v1 file, precedence, identities, bundles; `[mining] policy_file` |
| `347894c` | T067-003 | Migration032 bindings (immutable, RLS, grants), `mining.bind_policy`, schema/upgrade allowlists, 0.6.19 source |
| `a29ad62` | T067-004 | Admission capture (local and central), binding before the provider, enforcement on eight channels |
| `3e221de` | T067-005 | `rag extraction validate|inspect|dry-run`, shared `validate_source` |
| `47e7bf8` | T067-006 | Populated 0.6.19 → 0.6.20 upgrade rehearsal with actual old code |
| `048a9f8` | T067-007 | 0.6.20 version, reference doc, PB-067-OPS and its rehearsal, measurement script |
| final docs commit | T067-007 | Measured results, this record, playbook evidence sidecar, task checkboxes |

## What was measured, and what was not

The [measurement](../benchmarks/2026-11-01-extraction-policy/README.md) runs
seven frozen cases three times through actual mining with a mock provider at
`048a9f8`. All deterministic outcomes were identical and matched the frozen
labels. Three before/after examples:

1. R1 (EN): without a policy the batch kept 1 memory, 1 lesson and 1 signal; with
   policy A it kept the 1 decision memory, dropping the abandoned-experiment lesson
   and the error signal (`category_disabled`). 1 provider call either way.
2. D1 (DE): 2 memories, 1 lesson, 1 pin suggestion and 1 domain proposal became
   1 memory and 1 pin suggestion (`item_limit`, `body_limit`, `category_disabled`).
3. P1: after a provider outage and a file replacement, the retry used the
   admitted digest without reading the file (2 provider calls until acceptance,
   0 on replay, replay 4.00–4.43 ms); a new admission took the new policy.

Not measured: real-model extraction quality or guidance adherence. Case L1
records that an abandoned experiment labelled as an allowed memory is kept.

## Populated upgrade and recovery

`tests/service/test_extraction_policy_upgrade.py` (store written by the actual
0.6.19 code, 177 original rows in 47 tables): interrupted migration032 rolled
back; verified upgrade applied `032_extraction_policy.sql` in 2.67 s; empty
retry; original rows (including queue, batches, windows, lifecycle tables),
`ev1`/`src1`, grants, owners and sequences unchanged; 0 provider calls by the
upgrade; 0.6.19 reads identical and ordinary writes working on schema032 before
and after bindings; the old pending job mined under builtin rules although a
custom file was configured; the old accepted batch applied unchanged without a
file read and without a binding; a 0.6.19 miner kept 2 categories the captured
policy disables (activation gate required); post-upgrade backup restored with
its binding and trigger; pre-upgrade restore loses later writes.

## Requirement dispositions

| ID | Disposition | Evidence |
|---|---|---|
| AC-001 | Implemented | `tests/test_extraction_policy.py` (strict v1, bounds, codes/locations, identity) |
| AC-002 | Implemented | frozen `effective` labels, `rag extraction inspect` test |
| AC-003 | Implemented | `tests/test_extraction_cli.py` (0 calls/0 writes by default; explicit `--evaluate` 1 call, 0 writes; redaction) |
| AC-004 | Implemented within stated limits | eight-channel enforcement test, unchanged grounding in fixtures S1, L1 semantic limit |
| AC-005 | Implemented | binding-before-provider, retry/continuation/replay tests local and central |
| AC-006 | Implemented | legacy job/window tests, accepted legacy batch test, upgrade rehearsal |
| AC-007 | Implemented | shared validator, service-owned central capture, per-admission read, bind audit with digest only |
| AC-008 | Implemented | no re-mining command; replay tests; prospective rollback in PB rehearsal |
| AC-009 | Implemented; independent review pending | upgrade rehearsal, PB-067-OPS rehearsal, activation gate |
| AC-010 | Partially: fixtures, measurement and self-rehearsal done | independent review and fresh full suite are S2/S3 |
| AF-067-001..008 | Addressed in S1 as mapped in tasks.md | see the slice report |

## Deviations and limits

- One cursor has one meaning: if a new local job reaches a cursor that already
  has a binding from an earlier job, the earlier binding wins and an
  `extraction_policy_reuse` audit row names both digests (not silent).
- A malformed central snapshot ends the receipt as `error`/`processing_failed`
  (no dedicated public code); the local job records `policy_snapshot_invalid`.
- The binding audit adds one `audit_log` row per newly mined cursor; one earlier
  test that counted exactly one acceptance row now names both rows.
- `rag service job-retry` and PB-063 R1–R4 were not executed end to end in the
  playbook rehearsal; the central retry path is covered by service tests.
- The `PYGATE` rehearsal has one-second start-time resolution and can flake
  under load (observed once on the existing PB-065 rehearsal).

## Verification run

Serial targeted and affected suites at `048a9f8` (66 test files: all new RAG-067
tests plus mining, jobs, worker, hooks, ingest, source worker, queue, authority,
schema, every earlier upgrade and playbook rehearsal, backup/restore, store,
evidence and MCP): **626 passed, 0 failed, 1 known warning
(`StarletteDeprecationWarning`), exit 0, 703.78 s** on PostgreSQL 17.10, port
55460. The root full suite, Node, packaging and browser gates are pending at root.
