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

## RAG-006 fact validity (design-time, 2026-09-05)

- **AF-006 — Resolved; authority boundary (AC-002/005).** Mining windows currently
  flatten role/time/identity. `fact-validity.md` requires evidence matched against
  the consumed source fragment before acceptance. Task T002 must preserve this
  metadata and reject invented evidence; full #7 is not assumed implemented.
- **AF-007 — Resolved; concurrency/order (AC-001/006).** Read-then-write replacement
  races and arrival-time ordering can reverse truth. Task T001 must serialize a
  canonical assertion key, use event time, and keep all effects in the batch txn.
- **AF-008 — Resolved; shared eligibility (AC-004).** Search-only post-filtering leaves
  hooks/graph bypasses and exhausted candidate budgets. Task T003 must enforce one
  SQL predicate before limits and at every selected graph hop.
- **AF-009 — Resolved; lifecycle ownership (AC-003/007).** Whole-document curation
  could archive an assertion independently of valid time. Task T004 must exclude
  atomic assertions, reject in-place edits and establish explicit reactivation epochs.

Verification 2026-09-06: mapped changes implemented, as-built view reconciled,
independent review clean after source-authority/completeness, evidence retention
and reactivation fixes. Derived success/recovery tests pass in the full 703-test
suite. Next action: backup-gated rollout.

## RAG-007 evidence lifecycle (design-time, 2026-09-06)

- **AF-010 — Resolved; source authority (AC001/002/003).** Existing event IDs lack
  explicit session namespace at the attachment boundary. Task T001 namespaces
  identity and derives role/time from source; T002 grounds before batch acceptance.
- **AF-011 — Resolved; concurrency (AC003/004/007).** Attach and source withdrawal
  must not overwrite each other. Task T001 uses deterministic source locks and
  immutable append semantics; T004 proves replay and concurrent trust changes.
- **AF-012 — Resolved; eligibility (AC004/005).** Source trust must compose with
  temporal validity at every pre-limit/hop predicate, without reviving superseded
  values. Task T003 replaces the common predicate and proves composition.
- **AF-013 — Resolved; content ownership (AC006/007).** Ordinary updates/curation can
  invalidate attached evidence. Task T002 protects managed claims from in-place
  mutation and curation; legacy documents remain labeled incomplete.

RAG-007 reconciliation: AF010–013 implemented and covered by source lifecycle and
mining integration tests. Independent review findings on signal authority, confirmation
inheritance, malformed timestamps, completeness and prompt labels corrected with
regressions. Final independent fix review is clean; full verification passed (718 tests).

## RAG-009 design findings (2026-09-06)

- AF-009A(resolved;AC-004/005/006): visible revision + per-read eligibility and real-turn
  identity prevent stale corrections/replays. See rag009-context.md; tasksT001/T003.
- AF-009B(resolved;AC-003/004): budget/dedup ordering and whole multiline pins must remain
  faithful. See rag009-context.md; taskT005.
- AF-009C(resolved;AC-006/007): writer-only atomic refresh, dated fallback and source-backed
  stable classification. See rag009-context.md; tasksT001/T006.

RAG-009: independent final review Ready; real queue/worker/reader success and failed
refresh recovery pass. Full isolated suite:757 passed29.14s. See rag009-context.md.


## RAG-5.4 architecture findings

RAG-5.4 design/as-built reconciliation,2026-10-03. Evidence: [consistency sequence](contextual-indexing.md), [plan](../specs/RAG-5.4-contextual-indexing/plan.md), tests/test_contextual_indexing.py and the populated [rehearsal](../benchmarks/2026-10-03-contextual-indexing/results.json).

| ID | Question/risk | Requirement | Required task | State |
| --- | --- | --- | --- | --- |
| AF-5.4-001 | source edit/model switch during inference | AC-004 | fingerprint/lock, query and index digest races, scope/time/source eligibility tests | resolved; regression tests and old-writer recovery |
| AF-5.4-002 | index-only rebuild loses baseline/citations | AC-002/003 | side table + all15 canonical table fingerprints, historical audit subset, original spans | resolved; migration/index/recovery snapshots |
| AF-5.4-003 | old worker cannot process new jobs | AC-004/006 | unchanged queue vocabulary/scheduler; actual old save/read after015; queued reembed lexical context | resolved; coexistence and retry tests |

## RAG-5.5 design findings (2026-10-03)

Evidence: [transaction sequence](filter-aware-search.md), [plan](../specs/RAG-5.5-filter-aware-search/plan.md),013/015 candidate functions and psycopg transaction ownership.

| ID | Question/risk | Requirement | Required response | State |
| --- | --- | --- | --- | --- |
| AF-5.5-01 | budget/scan settings leak into caller or neighboring client | AC-001/003/005 | savepoint-local settings outside candidate statement; successful explicit restoration and real timeout/cancel recovery tests | resolved; actual success/timeout/cancel/discovery ownership tests and full987 suite pass |
| AF-5.5-02 | long-document chunks crowd out other eligible sources | AC-002/004 | exact eligibility materialization and per-document diversity before final limit; bounded ANN pool and separate oracle recall measurements | resolved; complete small-set oracle/ties4096/4097 and measured pool/source diversity; Trading exact-oracle/citation parity |

## RAG-5.8 entity identities (2026-10-04)

Named question: How can an operator reverse identity links without rewriting facts
or permitting scope/trust bridges? [Model](entity-identities.md),
[plan](../specs/RAG-5.8-entity-identities/plan.md), AC-001–008.

- AF-5.8-001: Preserve exact assertion keys and original validity functions; cross-name
  validity belongs only to the new explicit read. Required T002/T004; design addressed.
- AF-5.8-002: Relations bind one known scope/domain, complete active user evidence and
  explicit confirmation. A star has one anchor and no transitive chains. Required
  T003/T004; design addressed.
- AF-5.8-003: Old writes lack mapping; resolve exact rows directly and report missing
  indexing, backfill through gateway. Required T002/T006; design addressed.
- AF-5.8-004: Support and relation state must share the read snapshot; competing
  confirmations require ordered scope locks. Required T003/T004/T006; design addressed.
- AF-5.8-005: Code rollback retains018, source rows and old-client behavior. Backfill
  is bounded/replay-safe; strict backup restore precedes migration. Required T006;
  executed populated017→018/strict restore/code recovery evidence passes.


As-built RAG-5.8 reconciliation: [EI-S01–04 and EI-R01–03](entity-identities.md)
pass against current schema/CLI/MCP/source transaction contracts. Stable unindexed
IDs, complete original-span support, exact project/domain selection, bounded output
and retained018 rollback are evidenced. Initial automatic indexing design was
revised to explicit audited backfill after real source/batch deadlock regressions;
existing assertion/mining code is byte-identical to source. No open architecture
finding; production rollout remains separately authorized.
