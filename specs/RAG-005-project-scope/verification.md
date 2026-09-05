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
