# Change Design: Statement-local document permission inputs

## Context

`sql/021_service_scope.sql` defines `service_documents` through two calls to `rag_service_allows`, each reading the same JSON setting twice. Nested chunk and evidence policies also reach documents. The scope settings are fixed between statements, not inside a statement. The new expression SHALL preserve the original order and lazy inactive-service bypass. The parent architecture is unchanged.

## Interface contracts

| Boundary | Existing contract | Delta | Failure behavior |
|---|---|---|---|
| Document policy | Read domains/projects; write domains/projects in WITH CHECK | Four lazy scalar InitPlans feeding one pure helper | Same denial and SQLSTATE, no fallback |
| SQL helper | No new data authority | `rag_service_permission(text,jsonb)`, SQL STABLE, non-strict, invoker, default PARALLEL UNSAFE | No SET or SubLink in body; qualify `OPERATOR(pg_catalog.?|)` |
| Roles | reader, writer, admin and deployment readers may encounter RLS | Explicit PUBLIC EXECUTE on an argument-only Boolean helper, like original permission helpers | Grants no table access or privileged context |
| Upgrade | Verified backup, writers stopped, atomic migrations, preserved originals | Add 035 after unchanged 034 | Interrupted migration rolls back; retry is idempotent |

## Decisions

- Only `ALTER POLICY service_documents` USING/WITH CHECK changes; preserve policy OID, name, roles, command and permissiveness. Leave 021 helpers and every other policy unchanged.
- One use of each helper parameter permits inlining. The body contains only `COALESCE(p_permissions OPERATOR(pg_catalog.?|) ARRAY[p_value,'*'],false)`; no `SET search_path`, STRICT, definer or leakproof flag. Public execution is deliberate because inputs are supplied by the caller and no data is read.
- Do not cache, constant-fold or parse permission inputs at plan preparation. Generic plans must read the current settings on every execution.
- IR-1/IR-2 are requirements, not deferred findings. IR-4/IR-5 constrain scope and complete binding in tests.

## Explicit supersession of the locating heuristic

The coordinator prospectively supersedes the earlier 0.15 CPU-s per weighted job worth-doing heuristic and the diagnostic S3 stop rule. This is a change to implementation-selection policy, not a result of either INVALID characterization and not a relaxation of maintainer acceptance. No R2 confirmation or measured benefit is claimed.

Before the fresh in-change benchmark, fix this effectiveness gate: three paired rounds on one physical database/index, measured metadata/context/search inputs and scope bindings, actual backend CPU plus owned PostgreSQL cgroup coverage. Each round's weighted CPU saving MUST be strictly positive, and no job kind may consume more CPU than baseline in any round. The weights are 107/107/106 out of 320. Report raw timings, tick resolution and all round means; the range is not a confidence interval. No minimum magnitude is selected after measurement. Missing CPU coverage, exceptions, scope/parity drift, extra model calls or a changed input invalidates the benchmark; do not rerun automatically.

A pass only justifies proceeding to the existing physical gate. Physical search p95 MUST remain strictly below 11 seconds in every 40-client phase with background extraction, unchanged memory limits (4 GiB before BG start, 2 GiB both resident), complete 13-window drain, no fallback/model errors and the full correctness/authentication/resource oracle. A physical FAIL leaves #68/#92 and parent tasks open. Standalone shipping of this optimization then needs an explicit maintainer decision; no automatic merge, acceptance or further local RLS patch follows.

## Tests and ordering

1. Freeze the original policy fixture; characterize all three roles, settings/errors, nested visibility and scoped writes before runtime changes. Observe a red plan-work test on 034.
2. Add 035 and prove helper inlining, lazy InitPlans and unchanged point access. Test the reader/admin ACL and namespace shadowing.
3. Test prepared/generic live domain and project revocation with the complete initial GUC set restored, plus repeated hybrid function calls on the same connection.
4. Rehearse populated archived 0.6.21 upgrade, interrupt/retry, target backup/independent restore, and rollback/reapply. Extend the existing limited-owner rehearsal.
5. Independently review the complete bounded security diff; fix findings. Run the fresh effectiveness benchmark once, then affected/full/Node/build/lock checks and the parent physical gate in dependency order.

## Risks and rollback

Changing expression shape may alter lazy errors or plan shape. Any semantic difference, non-inlining, privilege change beyond pure-helper EXECUTE, or slower point access stops the candidate; do not widen semantics to pass a test. Rollback SQL restores the exact frozen 021 expressions, then drops only the new helper. Both operations are transactional and leave all knowledge/history/queues intact. Keep marker 035; explicit SQL reapply is required to re-enable it. Current schema validation and old-reader behavior must be tested in both states.

## Playbook obligations

PB06801 (system deliverable), coordinator owner, updated before delivery; source scenario is an existing-installation upgrade or a plan regression after upgrade. Require independent review plus actual populated upgrade/restore and rollback/reapply tests, including non-superuser owner. The existing isolated-copy procedure is sufficient for development; no new diagnostic harness or production operation is authorized.
