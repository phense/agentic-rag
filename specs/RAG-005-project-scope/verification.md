# RAG-005 verification and convergence

Full suite: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider`
**685 passed in 14.32 s**, after all application changes (2026-09-05).

AC-001: test_scoped_search_global_unknown_and_update,
test_scope_filters_before_candidate_limit_and_graph_recursion,
test_vector_candidate_scope_precedes_limit.
AC-002: normalization/worktree, wildcard pin, nested-repo and hook/startup tests.
AC-003: same-known curation, near-duplicate and model-time scope-repair tests.
AC-004: CLI/MCP project/global/all contracts and explicit unknown tests.
AC-005: additive 009→010 upgrade, reader privileges, audit/rollback/idempotence,
pin-phase rollback, conflict preservation and content freshness tests.
AC-006: versioned scope corpus and real isolated retrieval regression; no paid model call.

Independent review findings: four Important, each resolved with code and focused
regressions; see docs/uml/findings.md. Architecture-derived success/recovery flows
exercise real collaborating components. Source-vs-scope benchmark limitation is
explicitly rejected, not silently measured with different ground truth.

Convergence: no remaining application, interface, architecture or review findings.
Remaining operational work: backup/rollout, live invariant verification, scope
measurements, publication and issue closure. Existing main AGENTS.md untouched.

Operational gate: automatic approval review rejected the prepared canonical DB
rollout and integration because the general issue instruction was considered
insufficient authorization. The deployment command never executed. No backup,
migration, backfill or active-main integration was performed for issue #5.
Prepared script: /private/tmp/deploy-rag-issue5.py. Await explicit approval before
executing it. The read-only scope benchmark succeeded with zero selection violations
in both modes; artifacts are in docs/benchmarks/2026-09-05-project-scope/.

## Authorized rollout completed

After the initial approval-review rejection, the user explicitly authorized rollout
conditional on a current backup and requested verification of the backup agent.
Existing com.agentic-rag.backup was loaded (daily03:30), last run exit0; the latest
local/cloud archive was 68 minutes old. The existing backup function then created
a fresh `agentic_rag-20260905-232752.dump`; pg_restore list proved it readable and
local/cloud SHA-256 matched before any database migration.

Under the actual worker singleton lock: migration010 applied; 4,195 documents and
2 derived pin paths mapped. 3,896 documents retained unknown applicability. All
8,091 document contents, original provenance/meta, statuses and timestamps and
all 22 raw pins were fingerprint-verified unchanged. Backfill replay changed zero
rows; migration replay applied nothing. Main was fast-forwarded with AGENTS.md
unchanged. Installed code/reader scope query/worktree identity/status and actual
benchmark database cleanup were independently verified.

Wheel inspection confirms scope.py, migration010 and the eight-query fixture.
The earlier rejection and pending notes above are historical; rollout is complete.
