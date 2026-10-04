# Implementation Plan: Filter-aware vector retrieval

## Stable work ID

RAG-5.5, [specification](spec.md), Issue30. Base99514fe, worktree `.worktrees/adaptive-search`, branch `feature/filter-aware-search`.

## Summary

Add016 read functions alongside013/015. A bounded eligible-set probe chooses exact ordering for at most4096 matching vector chunks; larger sets use a maximum4096-neighbor ANN pool and existing two-chunks-per-document/50-vector-candidate policy. Initial thresholds are calibration candidates. No index rebuild or knowledge conversion.

## Project gates

| Gate | Evidence | Result |
| --- | --- | --- |
| Production isolation | Root clean99514fe; clean linked worktree reused at99514fe | Pass |
| Baseline | Existing absolute interpreter, candidate PYTHONPATH:960 tests40.06s | Pass |
| Source compatibility | Populated015, pgvector0.8.4/PostgreSQL17.10; reader inventory10448 documents/7domains/6scopes; Trading2926 eligible chunks | Verified read-only |
| Canonical state | Issue29 closed/adopted; Issue30 open | Sequential gate passed |
| Continuity tooling | No run tree exists; bundled state-check exits2: legacy BACKLOG has no parseable task IDs | Manual Git/Issue/artifact continuity; no successful CLI recovery/event claim |

## Technical context

Python3.13/psycopg; `search.py`, new `vector_plan.py`; migration016; existing store/config/MCP/CLI unchanged. PostgreSQL halfvec1024 cosine. One audited canonical store. The retained environment imports the worktree through PYTHONPATH; never reinstall the production editable package.

## Compatibility boundaries

Preserve old SQL functions and all stored data. New routing is only default context-auto candidate retrieval, after exact-selector routing; context-off/forced hybrid/baseline remain controls. New code on015 detects missing functions and uses the current path. Apply016 transactionally with bounded deployment lock timeouts; repeat is a no-op. Code rollback keeps016 inert. Production rollout/merge need their existing separate specific approvals.

## Interface contracts

| ID | Producer/consumer | Change | Failure behavior |
| --- | --- | --- | --- |
| IC-001 | search/SQL | New planned fusion when available | Missing016 retains015 |
| IC-002 | vector helper/SQL fusion | Exact small eligible set or bounded ANN, per-document cap before final50 | Missing iterative capability uses noniterative ANN; still bounded |
| IC-003 | planner/caller connection | Savepoint-local scan settings and statement budget, restore on exit | Roll back only savepoint on errors; preserve caller state and cancellation |

## Research and decisions

[pgvector primary documentation](https://github.com/pgvector/pgvector#iterative-index-scans) explains ANN post-scan filtering, iterative support starting0.8.0 and approximate max-scan limits. Capabilities must be checked from installed extension and registered GUCs. Strict ordering avoids relaxed-sort ambiguity. [PostgreSQL17 statement budgets](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-STATEMENT-TIMEOUT) must be set before issuing the candidate statement, not inside it. [psycopg nested transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html#nested-transactions) protect caller transactions.

Planning settings: ef_search256; iterative strict_order where supported; max_scan_tuples20000; scan memory multiplier1; candidate SQL statement timeout at most2000ms and never larger than an existing nonzero caller setting. Save originals and explicitly restore on successful release; failures roll back the savepoint. Caller-requested cancellation propagates. Timeout fallback, if delivered, must be separately bounded and must not bypass a stricter caller timeout. Prefer propagation over silently swallowing cancellation.

## Dependencies

Feature4 is fully adopted; no other roadmap dependency. PostgreSQL's installed extension provides optional capabilities; no upgrade is installed. Existing strict backup/owned-database helper is reused.

## Tests

Test-first real gateway fixtures with deterministic local-boundary vectors: exact eligible oracle, small project, rare/time/source filter, crowded long document, raw/current-context parity, stable ties/null/zero vectors. Probe large-route caps and unsupported capabilities on real collaborating SQL. Verify concurrent connections and autocommit/outer transaction settings; real timeout/cancel recovery preserves caller state. Rehearse actual015→016 interrupted/retry/repeat, actual old/new readers and code rollback; strict restore every canonical/derived table and grants on owned copies. Trading gets read-only fixed-time/oracle comparisons with sanitized aggregates only. Finish with full Python/Node suites.

## Architecture findings

AF-5.5-01: settings must be applied/restored outside the candidate statement, bounded by caller settings; cover error/cancel savepoint ownership. AF-5.5-02: exact diversity must precede final candidate limits; ANN caps are approximate limits, never advertised as an exact recall guarantee. Both are implementation/test obligations, not unapproved scope.

## Supporting artifacts

One sequence view under `docs/uml/filter-aware-search.md` answers transaction/settings/compatibility flow. No new persisted data-model artifact is needed.

## Implementation structure

Coordinator owns sequential SQL/Python/tests/measurements/upgrade playbook; independent reviewer owns review reports only. Shared SQL/Python contracts are not assigned to parallel writers.

## Playbook obligations

PB-5.5, system, `docs/filter-aware-search.md`, operator: migration, bounds, cancellation and code rollback; content review and actual populated rehearsal before PR readiness. Existing PB-5.4 strict backup method is reused; no new development infrastructure operation.
