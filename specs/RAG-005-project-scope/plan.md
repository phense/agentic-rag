# Implementation Plan: Consistent project scope

## Stable work ID
RAG-005; specification: spec.md. Accepted implementation sequence under the user's request.

## Summary and technical context
Python 3.13, PostgreSQL/pgvector. Add `documents.project_scope` (global, unknown,
or canonical absolute project root) plus `scope_explicit` (protect explicit decisions) and `pins.scope_path` (normalized path anchor).
One scope.py resolver/selection helper owns filesystem and Git worktree semantics.
Domains are unchanged. Existing absolute provenance.project values are candidates
for audited backfill; missing, relative, conflicting metadata is unknown. Explicit
project_scope is authoritative after resolution; original provenance and pins stay intact.

## Project gates
| Gate | Evidence | Result |
|---|---|---|
| Single store / audited writes | AGENTS.md, store.py | preserve; scoped repair is a store gateway method |
| RO tools remain RO | mcp_server.py, SQL roles | preserve; new retrieval SQL remains invoker-rights |
| Existing user changes | git status | main AGENTS.md untouched; temp worktree |
| No paid evaluation | accepted scope / previous budget boundary | deterministic SQL and local embeddings only |

## Interfaces and compatibility
- `scope.selection(project, scope)` yields SQL text[] or NULL. NULL means deliberate
  all-project selection; project means canonical Git root (or non-Git directory ancestors) plus global;
  global means only global. Unknown is never in scoped selection.
- CLI/MCP save add project/scope; no explicit scope plus unambiguous absolute
  provenance.project derives project. Absent scope on updates preserves it.
- Search/graph add optional scope arguments. SQL filters each vector/FTS candidate
  branch and every recursive graph hop, before LIMIT. Existing 4-argument SQL
  functions remain wrappers for old manual API compatibility.
- Pins preserve raw body/scope and use canonical scope_path for exact directory
  ancestry matching without LIKE wildcard semantics. Git worktree paths map to
  primary root plus relative directory for pins; document identity collapses to root.
- Hook recall uses scoped signal SQL plus matching pin IDs before LIMIT. SessionStart
  uses the same document selection plus explicitly applicable pin document references.
- Exact/near duplication and refute candidates require identical known project_scope;
  do not automatically curate unknown scopes or cross-scope mined edges.
- Migration 010 is additive. Audited backfill runs after it, is idempotent, preserves
  original provenance, and inventories unknown reasons in review. Backup before
  live application. Older application code can read columns but lacks isolation;
  never run old curation as a safe rollback.

## Dependencies and ownership
Scope resolver and migration precede gateway/backfill and read paths. Curation and
hooks depend on the shared selector. One coordinator owns implementation to avoid
shared-file races; a bounded independent review follows integration.

## Tests
- Pure paths: symlink, subdir, Git worktree, wildcard characters, missing/invalid paths.
- Real DB: adversarial >50 project B candidates, global/all and domain combinations,
  before-limit ranking, reader privileges, A-B-A graph bridging, exact/near curation,
  unknown isolation, hook pins, gateway updates and migration/backfill idempotence.
- Benchmark: versioned scope fixture corpus alongside existing baseline (no rewriting
  v1 labels); runner optional project/scope parameters recorded in comparison contract.
- Recovery: simulate backfill failure inside transaction, retry, retain original labels;
  migration additive and idempotent on existing schema. Full suite at convergence.

## Architecture findings
AF-001 pre-limit and every-hop filtering; AF-002 unknown scope must fail closed for
implicit context/curation; AF-003 preserve nested path pins through worktree aliases.
See docs/uml/findings.md and project-scope.md. No separate profile subsystem is created.
