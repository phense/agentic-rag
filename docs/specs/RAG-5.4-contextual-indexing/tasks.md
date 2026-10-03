# Tasks: RAG-5.4 contextual indexing

Sequential coordinator implementation; independent review is mandatory.

- [x] T001 (S1, AC-001/002/006) Write/run red builder and additive-schema/source-grounding tests in tests/test_contextual_indexing.py; implement contextual.py and sql015.
- [x] T002 (S2, AC-003/004/005; AF-5.4-001/002) Test then implement bounded idempotent index-only save in store.py and cli.py, source lock/fingerprint, model failure/replacement and privileges.
- [x] T003 (S3, IC-001/002) Test then implement candidate fusion, context auto/off CLI/MCP options, baseline/exact/old-schema compatibility and source scopes.
- [x] T004 (S4, AC-006/007; AF-5.4-003) Rehearse actual014→015 populated migration, interruption/rollback/recovery and old/new reader/writer coexistence. Test canonical fingerprints.
- [x] T005 (S4, AC-007) Publish three real-embedding practical paired measurements, original spans/context budgets and separate indexing costs; keep Trading private/read-only.
- [x] T006 (S5) Reconcile as-built architecture; independent system architect derives success/recovery integration tests; run full Python/Node suites and independently review until no Critical/High/Medium findings.
- [ ] T007 (PB-5.4) Document and review/rehearse operational upgrade/recovery procedure; update capability/backlog/Issue29 evidence; submit/link PR and ask specific merge approval.

T006 evidence:960 Python tests36.85s,7 Node tests; independent final review Ready with zero C/H/M/Low findings; architecture-derived success/recovery scenarios pass. T007 upgrade procedure reviewed/rehearsed and capability/backlog evidence updated; PR submission and specific merge-approval question are the remaining handoff actions. Production rollout remains separate.
