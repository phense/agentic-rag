# Project applicability

Project scope is context selection, separate from topic domains and PostgreSQL
permissions. One canonical store and both MCP privilege levels remain in use.

## Save and search

```bash
rag save --title 'Build repair' --domain programming --dtype lesson \
  --body 'Use the documented project repair.' --project /absolute/repository
rag search 'build repair' --project /absolute/repository
rag search 'build repair' --scope global
rag search 'build repair' --scope all
```

MCP `memory_save` and `memory_search` accept the same `project` and `scope`
parameters. Writes accept `scope=project|global|unknown`; reads accept
`scope=project|global|all`. A project path implies project scope; combining a path
with global/all/unknown is rejected. Omit both on existing manual searches to
preserve cross-project browsing. Automatic hooks never use that unscoped default:
they use the session project, or global-only when cwd is absent.

Global applicability must be explicit (`--scope global`). Without an explicit
selector, a new write may derive scope from unambiguous absolute provenance.project.
Missing, relative or conflicting project information stays unknown. Updates without
an explicit selector retain their scope, even when original provenance still names
an older project. Domain names never substitute for project boundaries.

## Identity and pins

Existing symlinks resolve to their target. A Git repository's primary checkout is
its canonical project; linked worktrees and subdirectories resolve to the same root.
A nested Git repository is a separate project. For non-Git directories, an absolute
normalized directory is an applicability anchor and descendants inherit it. Git
errors/timeouts do not permit additional ancestor document selection. Foreign
GIT_* environment variables cannot redirect detection. Identity follows local
filesystem evidence; moved/deleted repositories and paths from other hosts may need
explicit operator repair. No remote repository lookup is performed.

Pins retain their exact user-owned body and scope. A separate normalized scope_path
maps worktree-relative directories onto the primary checkout while preserving the
subdirectory suffix. Global and ancestor-directory pins match exactly, without SQL
LIKE wildcard expansion. Topic-domain pins remain available in explicit pin/review
interfaces but are not guessed from a cwd. Explicitly applicable document pins
remain an intentional override for startup document references; get/path without a
selector likewise remains deliberate browsing, not an authorization bypass.

## Retrieval and curation

Each vector/English/German candidate branch applies scope before its candidate
limit. `memory_neighbors` and `memory_path` optionally accept the same selector and
filter every graph hop, so an A→B→A bridge cannot traverse B in an A query. Explicit
`memory_get`, unfiltered graph browsing and timeline remain available. Startup
project assembly and error-signature recall share this selection. Future profile
assembly must also use it; no new profile engine is part of this change.

Exact duplicates, near-duplicate candidates and automated contradiction review
require equal **known** scope. Unknown documents are never assumed to belong to one
common project. Curation acquires ordered endpoint locks and rechecks its original
scope immediately before mutation, including after model responses. Explicit
cross-project graph edges can still be inspected through deliberate browsing; they
are not cross-project auto-refutation authority.

## Migration and repair

1. Back up the canonical database and hold the existing worker singleton lock.
2. Apply `rag init-db` with this version (migration 010).
3. Run `rag scope backfill` once through the writer gateway, and inspect its report.
4. Re-run to confirm idempotence, then use `rag scope report` for unresolved rows.
5. Activate the matching code before releasing the worker lock.

The backfill maps unambiguous absolute provenance.project and derived pin paths.
It does not change original provenance, raw pin scopes/bodies or content freshness
(`updated_at`). Documents and pin-path repairs share one transaction; failures roll
back scope and audit changes. A concurrent explicit repair wins over backfill.
Explicit choices, including unknown, are marked scope_explicit and never promoted
by a later legacy backfill. Missing/conflicting information is reported; no global
classification or historical extraction is inferred.

```bash
rag scope report
rag scope set DOCUMENT_SLUG --project /absolute/repository
rag scope set DOCUMENT_SLUG --scope global
rag scope set DOCUMENT_SLUG --scope unknown
```

Restart long-lived MCP clients/servers to load the new tool parameters; CLI and
new hook processes load the installed code immediately. Existing unscoped manual
MCP calls retain their compatibility behavior.

The migration is additive and replay-safe. Old code can still access the schema,
but it does not enforce scope: **do not run old curation as a safe rollback**.
Prefer a forward fix with workers stopped; a database restore uses the verified
backup and normal restore procedure. Backfill does not rewrite knowledge text or
call an external provider. Unknown facts remain visible through explicit all-scope
search and get, and through the scope review inventory.

## Verification and benchmark

The fixture `agentic_rag/benchmark/corpus-scope-v1.json` contains identical error
signatures with conflicting project facts, global and unknown entries, and eight
labeled selections including deliberate cross-project and global-only queries.

```bash
rag benchmark run --corpus agentic_rag/benchmark/corpus-scope-v1.json \
  --search-mode fts --output /tmp/rag-scope-fts
rag benchmark run --corpus agentic_rag/benchmark/corpus-scope-v1.json \
  --search-mode hybrid --output /tmp/rag-scope-hybrid
```

Reports record per-query project/scope and preserve equal-budget comparison guards.
The scope corpus requires retrieval mode: scoped E2E mining overrides are explicitly
rejected before database/provider work because production mining cannot yet express
all global/unknown fixture choices. Existing unscoped E2E benchmarks remain supported.
Tests also cover >50 foreign candidates in both retrieval paths, role enforcement,
Git aliases/nested repos/timeouts, graph bridges, hook pins, concurrent scope repair,
and migration failure/retry. No new paid model matrix is required to prove isolation.
