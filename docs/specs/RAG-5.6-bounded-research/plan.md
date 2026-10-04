# Implementation Plan: Bounded research retrieval

## Stable work ID

RAG-5.6, [specification](spec.md). Worktree `.worktrees/bounded-research`, branch `feature/bounded-research`, base19ed09c.

## Summary

Add research.py coordinator and research_worker.py isolation boundary. Parent enforces the wall deadline over connection, local embedding, SQL and provider stalls, preserving ordinary search code and its latency. Worker owns a fresh repeatable-read, read-only reader connection and bounded in-memory evidence; progress packets retain safe partial results on timeout. The existing search/provider functions remain unchanged; a research-only runner disables provider tools, web, plugins, skills and MCP inheritance while retaining the configured authentication. Unsupported CLI isolation flags fail closed.

## Project gates

| Gate | Evidence | Result |
| --- | --- | --- |
| Isolation | clean canonical19ed09c; ignored linked worktree | pass |
| Existing source | reader inventory:16 migrations,10448documents/11838chunks/7domains/22pins; pgvector0.8.4 | verified read-only |
| Prior feature | Issue30 closed, private rollout-report confirms19ed09c/schema016 adopted | pass; reconcile historical local index in this PR |
| Baseline | full Python and Node commands in baseline log |987 Python/7 Node passed; final candidate1039 Python/7 Node passed |
| State tooling | no .engineering-method run tree; bundled state-check exits2 on legacy BACKLOG task IDs; no repository-local wrapper | Git/Issue/planning artifacts provide continuity; no successful event/recovery claim |

## Technical context

Python3.13, psycopg, configured Codex/Claude seam; no dependencies added. Canonical absolute interpreter retained, worktree selected with PYTHONPATH. Schema remains016. Parent subprocess group prevents a blocked provider/embedding/DB call from escaping the total wall deadline.

## Compatibility boundaries

Add rag research/memory_research; preserve every old tool/CLI argument/result. No migration/reinstall/config/service mutation. Old/new clients and rollback measured on a populated gateway-seeded multi-domain/multi-project installation. All research reads use rag_reader; application writes zero.

## Interface contracts

IC-001 returns structured partial evidence with explicit abstention. IC-002 validates all untrusted provider indices, exact quotations, source independence and limits; failed planning/checking falls back to local evidence and abstains. IC-003 uses private stdin, empty temporary cwd and nested TMPDIR, process group cleanup and one bounded serialized context; final packet includes logical step/call usage. Calls count retrieval, graph and structured-provider operations (their internal SQL/HTTP/subprocess work is bounded by wall time, not counted as separate API calls). Steps count plan/collect/check rounds; at most4 rounds by default.

## Dependencies

Existing search, source evidence, graph/temporal eligibility and llm.run_structured; all available at source016. No external provider used without explicit invocation choice. Corrective queries cannot modify filters, budget or provider.

## Tests

Test-first source-backed quotes, compound decomposition, no provider default, independent-source dedup, late relevant graph chunks, scopes/time/privacy, malformed model output and quotes, context/step/call/failure caps. Real subprocess deadline, descendant cleanup, cancellation and retry. Populated old/new CLI/MCP compatibility with full-row/privilege/config invariants; canonical read-only Trading aggregate controls. Full pytest and node --test tests/test_opencode_plugin.mjs. Final results and independent-review dispositions are in [verification](../../verification/bounded-research.md).

## Architecture findings

AF-5.6-01: bounded cooperative calls cannot enforce wall-time across existing120s embedding/300s provider paths; use a parent-owned worker/process group. AF-5.6-02: multiple documents are not independent sources; count retained active reviewed complete user-source keys backing exact quotes. AF-5.6-03: graph discovery must reapply both endpoint boundaries and rank full bounded chunk candidates. All mapped to tests/tasks.

## Supporting artifacts

Sequence model: docs/uml/bounded-research.md. No persisted data-model change.

## Implementation structure

Coordinator owns implementation/tests/evidence sequentially. Independent reviewer receives complete base-to-head diff and requirements, writes only its review report. No parallel implementation.

## Playbook obligations

PB-5.6 system, docs/bounded-research.md, operator, AC-001/003/005; content review and populated local recovery rehearsal before PR. No critical development migration operation: additive code-only release; production adoption requires separate authority.
