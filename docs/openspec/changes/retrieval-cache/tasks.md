# Tasks: Query inference reuse

Stable work ID5.2; Issue #27; base f27acd9. No new schema or production operation.

- [x] C001 Observe meaningful red repeat-query and immediate-correction tests.
- [x] C002 Implement bounded transport/query reuse with fresh model and SQL eligibility.
- [x] C003 Verify concurrency, scope/domain/role, digest/TTL/eviction, failures and lifecycle.
- [x] C004 Run full suites and populated read-only/code rollback checks.
- [x] C005 Measure three practical before/after examples and publish numeric limits.
- [x] C006 Independent complete review; fix/re-review all Critical/High/Medium findings.
- [ ] C007 Create/link PR, obtain specific approval before merge; adoption remains separate.

Full suite864 passed in33.56 s; Node7 passed. Populated multi-user/multi-domain
coexistence/rollback retains all public table rows. Independent final review has
zero unresolved Critical/High/Medium/Low findings; see review.md and numerical evidence.
PR #38 submitted and linked to the T3 thread. Specific merge approval is pending.
After approval/merge, continue feature5.3 / Issue #28 (local multilingual reranking).
The retained production checkout remains0c8addd; no adoption/restart/migration was performed.
