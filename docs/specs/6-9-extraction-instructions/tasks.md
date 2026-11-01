# Tasks: Versioned extraction instructions

## Stable work ID

Feature6.9 / RAG-067 / [Issue67](https://github.com/phense/agentic-rag/issues/67), roadmap9of15.
[Specification](spec.md), [plan](plan.md), [design](../../uml/extraction-policy-67.md).
Baseline01bc13bd /0.6.19/schema031; target0.6.20/schema032.

## Architecture findings and ownership

AF-067-001..008 in [findings](../../uml/findings.md) precede this task list.
S1 is one cohesive serial implementation: validator, admissions and retries share
one snapshot contract and must not be split across concurrent product writers.
S2/S3 are coordinator-owned integration and acceptance. No parallel pytest.

| Finding | Implementation task |
|---|---|
| AF-067-001 | T067-002 |
| AF-067-002 | T067-003/004 |
| AF-067-003 | T067-004 |
| AF-067-004 | T067-003/004 |
| AF-067-005 | T067-002/004 |
| AF-067-006 | T067-005 |
| AF-067-007 | T067-003/006/007 |
| AF-067-008 | T067-001/007 |

### Slice S1: Durable file-configured extraction with an upgrade path

- [x] T067-001 [AC-010] [AF-067-008] Freeze small synthetic EN/DE policy/source/expected-label fixtures before product code under `docs/benchmarks/2026-11-01-extraction-policy/fixtures/`; add checksums and explicit model-quality limits. Include source-event fidelity, category exclusion and changed-policy retry.
- [x] T067-002 [AC-001/002/004/007] [IC-001] [AF-067-001/005] Test first then implement strict bounded v1 policy models/file resolution/digest/precedence in `agentic_rag/extraction_policy.py` and optional path in `config.py`; cover malformed/duplicate/unknown/empty/forbidden combinations, secret-safe errors and unchanged no-custom prompt behavior. Document concrete caps, array replacement and domainless precedence.
- [x] T067-003 [AC-005/006/009] [IC-002/005] [AF-067-002/004/007] Test first then add `sql/032_extraction_policy.sql`, immutable bounded `extraction_policy_bindings` with session RLS, grants and atomic binding audit. Update `schema.py`, upgrade/restore allowlists. Preserve SQL001..031 and every existing source row; concurrent pre-provider bind has one committed winner.
- [x] T067-004 [AC-004/005/006/007/008] [IC-002/003] [AF-067-002/003/004/005] Test first then wire local `jobs.enqueue_mine`, central `service.ingest.accept`, local/central workers and `mining.mine_session`. Capture only permitted bundles at admission; retain through continuation/provider failures; accepted legacy batch wins before file reading. Enforce all eight output channels/limits, unchanged grounding and atomic gateway, all-disabled zero calls, current auth revocation and no silently acknowledged truncation.
- [x] T067-005 [AC-002/003/007] [IC-001/004] [AF-067-006] Test first then add `rag extraction validate|inspect|dry-run`, pure shared validation API and explicitly opted-in no-write provider evaluation; safe sanitized outputs, no default provider/embedding/gateway calls. Clearly reject unsupported client-mode operations rather than using wrong local service policy. No dashboard UI or new remote admin endpoint required.
- [x] T067-006 [AC-006/009] [IC-005] [AF-067-007] Rehearse actual archived0.6.19 `01bc13bd` populated source →0.6.20/schema032 on owned PG55460, including old pending/accepted work, ordinary old/new reads/writes, original rows/ev1/src1/grants/owners/sequences, migration interruption/retry and independent pre/post restore. Add `tests/service/test_extraction_policy_upgrade.py`; update previous migration-count expectations accurately. No production.
- [x] T067-007 [AC-005/007/009/010] [AF-067-007/008] Author PB-067-OPS and reader guide/reference, benchmark three frozen repetitions through actual mining with mock provider, report retained/rejected/source checks/call counts/latency. Write `docs/playbooks/system/rag-067-extraction-policy.md` with review sidecar and executable owned-copy CLI/service rehearsal: all-miner activation gate, invalid-file recovery, bound retry, prospective file rollback and restore limits. Update `docs/verification/issue67-extraction-policy.md`; exactly+1patch0.6.20 in pyproject/uv.lock/README/CHANGELOG. Run targeted and affected suites serially; commit clean and report concerns.

### Slice S2: Reconcile and independently accept integrated behavior

- [x] T067-008 [AC-001..010] [IC-001..005] Reconcile as-built code and design, record every difference and all AF dispositions. Independently review complete base→head bounded diff, schema/RLS/policy trust/queue replay/concurrency and PB content. Derive a plan before executing ACF-067-S success and ACF-067-R recovery against real collaborating components/owned DBs. Fix all Critical/High/Medium and Important playbook defects; collect Low in Issue75. Re-review changed risk boundaries proportionally.

### Slice S3: Converge, verify and deliver

- [x] T067-009 [AC-009/010] Run source-bound full pytest serially plus appropriate Node/lock/wheel/docs checks after final relevant fixes. Inspect terminal exits, warnings/skips/source hashes and actual populated upgrade/restore artifacts. Perform convergence against every AC/IC, current as-built, clean review and PB evidence; route gaps through this same work ID.
- [ ] T067-010 Synchronize Issue67/BACKLOG/FEATURES, create focused PR with tested upgrade/recovery and2–3 measured examples; link full URL immediately after creation/each push. Verify exact head/base/checks and merge autonomously under explicit remaining6.x permission only after all gates. Watch/end turn if blocked on CI. Report step9of15 then continue Issue68, inspecting existing plugin branch/work first. No production rollout inferred.

## Dependencies and acceptance

T001 →T002 →T003 →T004 →T005 →T006 →T007 →T008 →T009 →T010.
Every task is serial; S1 owns all shared interfaces and no other agent writes
product files concurrently. Red/green logs must be observed before each meaningful
behavior change, not reconstructed later. Existing accepted-output/authority tests
remain effective; changing tests to hide a regression is forbidden.

PB-067-OPS is a system-delivery dependency of T008..010. Draft, independent content
review and actual owned rehearsal are separate facts. No live deployment is part
of S1. A benchmark using predetermined provider output proves policy enforcement
and retry, not real-model semantic accuracy. Preserve failed artifacts and report
limits rather than inventing model quality or unmeasured host readiness.
