# Implementation Plan: Grounded contextual chunk indexing

## Stable work ID

RAG-5.4 / Issue #29. Specification: [spec.md](spec.md). Base499c656.

## Summary

Add `chunk_contexts` version1 alongside unchanged chunks. Deterministic prefixes (maximum768 characters) carry a title, document opening, active Markdown headings, section lead and explicit project name. Headings in code fences are excluded. Contextual representation is prefix plus original chunk content; search returns only original content. No synthesized dates/units.

Normal `store.save_document` builds lexical contexts in its existing transaction with no new embedding request. Explicit `rag save --index-context SELECTOR --index-limit 8` refreshes up to8 chunks (cap32) through the same gateway; pending selection supports repeatable maintenance. Only this bounded operation creates contextual vectors using existing local Ollama and a fresh model digest; unavailable/changed identity retains lexical context. No new worker job type.

## Project gates

| Gate | Evidence | Result |
| --- | --- | --- |
| production isolation | existing linked worktree, branchfeature/contextual-indexing; root499c656 untouched | pass |
| baseline | 930 Python tests36.00s | pass |
| gateway | store.py owns normal and index-only save; no script inserts canonical rows | required |
| compatibility | additive015; original013 candidate function retained | planned rehearsal |
| independent review | complete bounded diff + populated evidence | required before PR merge |

## Technical context

Python3.13.12, PostgreSQL17, halfvec1024, existing bge-m3/Ollama, no dependency/configuration changes. Paths: contextual.py, store.py, search.py, cli.py, mcp_server.py, sql/015_contextual_chunks.sql, tests/test_contextual_indexing.py.

## Compatibility boundaries

Migration015 adds only a side table, grants and new functions/indexes. No persisted backfill in migration. Normal old writers replace raw chunks; FK cascade clears their dependent contexts. New reads validate source revision and model identity. New code on014 detects absence and uses original search/save. Old code on015 retains original013 function and raw embeddings. Code rollback requires no data restore or derived-table deletion.

## Interface contracts

| Contract | Producer/consumer | Change | Failure |
| --- | --- | --- | --- |
| IC-001 | SQL candidate fusion → search.py | additive contextual function; context_mode keyword | absent015→baseline; stale context excluded |
| IC-002 | CLI/MCP → save_document | explicit index-only call, normal fields unchanged | reject mixed mutation; generic unavailable/model warnings |
| IC-003 | contextual builder → audited SQL function | prefix/source fingerprint/vector arrays, document-scoped | stale revision or lock conflict aborts safely |

## Dependencies

Existing model-digest function and embedding path; no cloud inference or new model. Source hash is computed in PostgreSQL from canonical fields and chunk text, checked again under document lock before derived writes. Prefixes are secret-stripped. Context is indexing metadata, never an authority boundary.

## Tests

Builder grounding/fences/bounds; original citation spans; lexical/vector ranking; baseline and missing-schema behavior; grants/read-only; source/model changes; interrupted/idempotent refresh; immutable claims; exact routing; CLI/MCP contracts. Full Python/Node suites. Populated014→015 migration, old/new writers/readers, restoration and code rollback on owned scratch DB. Three source-labeled practical comparisons with real local embeddings; private Trading inspection only read-only, derived writes on isolated representative data.

## Architecture findings

AF-5.4-001: prevent stale derived context after source changes → source fingerprint/lock tests.
AF-5.4-002: avoid losing baseline or citation identities during backfill → side-table-only gateway and all-table fingerprints.
AF-5.4-003: preserve mixed version worker semantics → no new queue kind or scheduler change.

## Implementation structure

S1 test-first builder/schema; S2 audited gateway and bounded CLI maintenance; S3 current contextual candidate fusion/contracts; S4 populated upgrade/recovery and numeric examples; S5 independent review, as-built reconciliation and PR evidence.

## Playbook obligations

PB-5.4 `docs/contextual-indexing.md`: source/target, backup/preflight, migration/index order, retry/resume, source-code rollback and explicit snapshot recovery loss limits. Readiness before merge; independent review and actual isolated rehearsal. Normal code edits use existing Git/PR workflow; no separate development-operation playbook needed.
