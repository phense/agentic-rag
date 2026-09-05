# RAG-005 architecture findings

- AF-001 (implemented; AC-001/003): Post-filtering loses eligible candidates and recursive
  traversal can bridge through B. Evidence: 003_search.sql LIMIT50, 004_graph.sql
  recursive walk; project-scope.md. Require scope in each candidate and hop (T003).
- AF-002 (implemented; AC-003/005): Unknown provenance cannot imply global or shared
  dedup identity. Evidence: curation.py domain/body join. Require explicit unknown
  state, equal-known curation and audited repair (T002/T004).
- AF-003 (implemented; AC-002): Repository-level collapse would broaden subdirectory pins.
  Evidence: pins.py prefix policy. Keep mapped directory anchor separately from
  project root; no LIKE wildcards (T002/T004).

2026-09-05: design evaluated against current code. Next: implement referenced tasks,
reconcile as-built, then independent architecture-derived success/recovery checks.

As-built reconciliation: scope.py owns root vs pin-anchor normalization, including
separate nested Git repos. Migration010 carries before-limit candidate and every-hop
filters. search/graph/CLI/MCP/hooks all pass selection; curation uses equal known
project_scope. store.set_project_scope and scope.backfill are atomic/audited and
preserve original provenance/content freshness. tests/test_scope.py covers bridge,
limit, hook, curation, path and retry flows. No diagram topology drift.

Independent architecture/code review (read-only reviewer): every candidate branch
and graph hop matches the model. Derived success flow maps to
`test_prompt_recall_and_startup_share_project_policy`; recovery maps to
`test_audited_legacy_mapping_and_rollback` plus pin-phase rollback. Added explicit
CLI/MCP roundtrip coverage. Four Important findings were dispositioned:

- Update replay of old provenance must not undo explicit repair: restrict automatic
  provenance inference to creates; regression reproduced before fix.
- Curation scope can change during model work: acquire ordered endpoint row locks
  and revalidate expected known scope immediately before writes; count/audit applied
  results only. Separate-connection scope-change regression covers the race.
- Git timeout is unknown, not proven non-Git: no ancestor document selection on
  failed detection; environment cannot redirect Git identity.
- Scope ground truth is not representable by current mining corpus overrides:
  reject scoped E2E benchmark mode before DB/provider work; existing unscoped E2E
  remains supported. Scope fixtures run through real retrieval mode.

As-built addendum: explicit scope decisions (including unknown) are protected from
legacy backfill by scope_explicit. Applicability-only changes retain updated_at.
All fixes stay within the defined data/applicability boundary; no extra reviewer or
paid model matrix was used.
