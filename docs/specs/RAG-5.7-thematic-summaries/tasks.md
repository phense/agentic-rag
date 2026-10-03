# Tasks: Thematic summaries

RAG-5.7; [spec](spec.md), [plan](plan.md), [verification](../../verification/thematic-summaries.md).

- [x] T001 Verify source revision, schema, roles, providers, client settings, previous adoption and baseline suites.
- [x] T002 Observe missing-gateway red test; implement additive cache and versioned extractive gateway.
- [x] T003 Extend profile worker/context, CLI and reader MCP; exercise malformed, source/time/project/domain, concurrency and failure boundaries.
- [x] T004 Independently review complete diff; reproduce and fix commit=False and context omission findings with red/green regressions.
- [x] T005 Rehearse populated016→017 interruption/retry, strict source/candidate backup restore and actual old/new/rollback clients; measure three paired scenarios.
- [x] T006 Verify private production-snapshot recovery and aggregate costs; finalize procedure/docs and full Python/Node results.
- [x] T007 Complete independent procedure/full final diff review; publish linked [PR45](https://github.com/phense/agentic-rag/pull/45) and Issue evidence.
- [ ] T008 Obtain specific PR merge approval; keep Issue32 open for separately authorized rollout evidence.

Order is T001→T002→T003→T004→T005→T006→T007→T008. Implementation is
sequential. The independent reviewer owns no implementation files and makes no
database/provider calls. Merge approval does not authorize017 production migration.
