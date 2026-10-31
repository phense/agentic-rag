# Tasks: Opt-in pattern synthesis

## Stable work ID

Feature6.7 / RAG-065 / Issue65 / step7of15; [specification](spec.md), [plan](plan.md), artifact `docs/specs/6-7-pattern-synthesis/tasks.md`. One serialized implementation owner; no parallel shared database fixtures.

## Architecture findings

- AF-065-001 (AC-002/003/004/006, IC-001/003): original-event independence, portable evidence identity and permanent anti-recursion. Owner S1; verify direct get/search/graph and later-confirmed patterns cannot bypass invalidation.
- AF-065-002 (AC-005/007, IC-002): accept before apply, unique identity and bounded retry under the existing worker. Owner S1; inject post-accept failure and audit rollback.
- AF-065-003 (AC-001/006/008/009, IC-001/003/004): scope/policy authority on preview, deferred application and reads; additive upgrade without automatic synthesis. Owner S1; scoped service and old-code probes.

## Tests

All pytest uses existing owned PG55460, never5432. `TMPDIR=/dev/shm/rag65-20261031-tests`, `PYTHONDONTWRITEBYTECODE=1`. Test fixtures reset a shared test database, so exactly one pytest process at a time. Independent probes use their own owned databases. Providers mocked unless explicitly running a declared synthetic-only measurement. Observe meaningful failing tests before implementation and retain actual exit/log artifacts; no post-hoc red reconstruction.

## Implementation slices

### Slice S1: Bounded, authorized, source-linked suggestions and safe upgrades

- [x] T065-001 [US-001/002] [AF-065-001] Freeze versioned synthetic known-pattern, duplicate/assistant/manual/derived false-pattern, contradictory and held-out fixtures before application edits. Record fixture hashes and expected supported/unsupported/non-conclusion labels; inspect real gateway/evidence/worker interfaces and settle exact contract/ownership before coding. Files: new benchmark fixtures and `contracts/pattern-v1.md`. Evidence: fixture-first commit and source-seam analysis.
- [x] T065-002 [US-001/003] [AF-065-002/003] Write failing tests for default-off/provider-free preview, scoped opt-in forward boundary and explicit bounded backfill; implement additive030 storage/RLS and schema/config/upgrade-source support, finite policy/work state, gateway methods and existing-worker scheduling. Files: synthesis core, SQL, config, jobs/worker and relevant service seams. Depends T065-001. Evidence: red/green, zero migration/provider activity, current authority and ordinary-worker behavior.
- [x] T065-003 [US-002/003] [AF-065-001/002] Test then implement eligible original selection, event/quote deduplication, exact versioned part citations, structured bounded provider use, accepted-result persistence, stable application identity and atomic inference/dependency/audit application. No pattern is a user statement; each suggestion meets the independence floor; ambiguous/conflicting/unsupported outputs are rejected or explicit non-conclusions. Depends T065-002. Evidence: real PostgreSQL identity/concurrency and post-accept retry/audit rollback tests; exact provider call counts.
- [x] T065-004 [US-003/004] [AF-065-001/003] Test then implement current dependency and policy validation for ordinary retrieval, direct reads, graph/derived views and pattern drill-down, including later-confirmed inferences. Cover source correction/ABA/expiry/supersession, scope/credential revocation, disable/re-enable and anti-recursion. Wire shared local CLI/MCP, REST/server-MCP and remote CLI/client proxies, preserving old signatures and RO surface. Depends T065-003. Evidence: transport parity and adversarial real-component tests.
- [x] T065-005 [US-001/003/004] [AF-065-003] Rehearse populated0.6.17/schema029→0.6.18 migration in standalone and central modes, actual old-code reads/feature-off rollback, all original field hashes/grants/history, independent backup/restore, empty retry and accepted-job recovery. No old-code import from new cwd. Files: isolated upgrade tests and evidence harness. Depends T065-002..004. Evidence: actual exits/owned cleanup and explicit post-write restore limits.
- [x] T065-006 [US-002] Run frozen-fixture evaluation and inspect2–3 actual output examples. Publish supported/unsupported part counts, false/conflict non-conclusions, provider usage, timings and finite-resource observations; distinguish mocked correctness from actual-model quality. Files: benchmark harness/results/README and verification guide. Depends T065-003..005. Evidence: reproducible commands, samples, hashes and limitations, no private data/new model downloads.
- [x] T065-007 [FR-005] Deliver PB-065-OPS and concise pattern user/config/tool docs using the relevant installed writing/playbook skills. Rehearse preview/enable/status/accepted-recovery/disable commands on owned fixtures; update exact0.6.18 pyproject/uv.lock/README/CHANGELOG. Run all new and affected neighboring suites once, inspect diff and write implementation report. Depends T065-005/006. Coordinator owns review and task/state completion, not implementer. Evidence: actual targeted results and playbook rehearsal artifacts; no full-suite claim, PR, merge or production operation from S1.

## Dependencies

| Work | Depends on | Reason | Parallel-safe |
|---|---|---|---|
| T065-002 | T065-001 | Fixture and contract first | None |
| T065-003 | T065-002 | Durable policy/batch and audited gateway | None |
| T065-004 | T065-003 | Shared evidence/dependency interface | None |
| T065-005 | T065-002..004 | Complete migration and client behavior | None |
| T065-006/007 | T065-003..005 | Measured final behavior and recovery | None |

## Final integration

### Slice S2: Reconcile architecture and independently review the complete feature

- [x] T065-008 Coordinator verifies actual implementation report/commits, diffs, test exits, all AC/IC coverage and as-built sequence/findings. Resolve concrete integration defects with tests.
- [x] T065-009 Independent strong reviewer reads the complete base-to-final diff and requirements, derives and executes at least one collaborating-component success and failure/recovery probe, reviews SQL/RLS/authorization/concurrency and PB-065-OPS content/rehearsal. No product/state/GitHub writes by reviewer. Coordinator fixes every Critical/High/Medium finding and packages changed ranges; Low findings go to Issue75.

### Slice S3: Convergence, full verification and PR handoff

- [ ] T065-010 Coordinator runs speckit-converge against actual as-built, integration, review, playbook, evidence and task state; route gaps back into this executor. Execute final full pytest and relevant Node suites, inspect actual completion/exit, wheel/SQL/assets/version and links. A running suite is not passing.
- [ ] T065-011 Synchronize numbered backlog/capability index and GitHub Issue65 with actual evidence, create one focused PR linked to65, link it to this thread immediately, report step7of15 and2–3 measured examples. Await a new maintainer weiter before merge. No deployment is included.

## Playbook obligations

PB-065-OPS: `docs/playbooks/system/rag-065-pattern-synthesis.md`, S1/T065-007 authoring and executable isolated rehearsal; S2/T065-009 independent content review; delivery blocked until both pass. Includes0.6.17 populated upgrade and accepted-job recovery. No development live-operation playbook is required because this issue performs no live rollout. Reassess if that scope changes.

### Slice S4: Review-driven correction before final integration

- [x] T065-012 [R65-02/03/06] Replace heuristic forward consumption with commit-safe processed membership, budget-fitting batches, visible recoverable oversized support and bounded recent cross-run context. Observe regression reds for held-open transactions, default12000-character budget overflow and recurrence spanning two runs before implementing. Preserve scope/RLS, epoch boundaries, zero-activity defaults, atomic accepted/application behavior and finite backfills. Extend additive030, schema/upgrade restore allowlists and populated-copy tests if storage changes. Run all affected synthesis/worker/upgrade tests serially and report actual exits.
- [x] T065-013 [R65-04/05, PB065-R01..06, R65-L2] Reconcile contract/user/benchmark/playbook text with the corrected spec and scheduling behavior. Require observable all-reader0.6.18 upgrade/restart before activation; forbid code-only rollback after patterns exist; rehearse central accepted-run recovery and the supported restore boundary. Preserve frozen fixture hashes; distinguish cited from semantically supported/unsupported parts and retain the C2 false suggestion. Align application identity text with semantic policy parameters. Re-run measurement on a clean identified revision and publish actual evidence without a real-model quality claim. Coordinator retains independent re-review and full final suite; neither is satisfied by this slice.

### Slice S5: Close remaining backfill and installation-gate defects

- [x] T065-014 [N1, PB065-R07/08] Keep a budget-blocked backfill pending without creating a run or advancing its cursor/batch allowance; expose the waiting reason through status and CLI, and resume after the budget is raised. Rehearse B0 with a real hardlink whose cache mtime predates the old reader, use the later of metadata mtime/ctime for each environment, and document the due-interval retry delay. Preserve regression red/green evidence, existing populated upgrade/recovery checks and independent acceptance of the changed integration boundary. Record N2/N3/N4 and retained Low findings in Issue75. No live rollout.


## Execution evidence and remaining delivery gate

T065-001..009 and T065-012..014 are implemented and independently accepted
through `73ddd02`: fixture-first `84bce47`, actual populated old-code upgrade
and restore rehearsals, final 60-file review, 34/34 fresh final assertions and
explicit reuse of unchanged earlier integration probes. All C/H/M and Important
findings are closed; LOW-038..044 remain in Issue75. The S5 regression tests
were observed red before the corrections and then green. Earlier S4 red logs
were reconstructed against prior source and are disclosed as a process
deviation, not original test-first evidence. Current behavior is backed by
independent probes and affected suites; no retrospective TDD claim is made.

T065-010 remains open until the actual full-suite exit/result after the restore correction is
inspected and convergence is accepted. T065-011 remains open until the focused
PR is created and linked, with the maintainer's specific merge approval still
required afterwards. No live rollout is included.

### Slice S6: Final full-suite restore regression

- [ ] T065-015 [AC-009, IC-004, R65-FULL-01] Preserve exact relation/default ACLs across the existing in-place `rag restore` path. Reproduce restore followed by dashboard browsing; protect all-or-nothing restore when SQL fails or the archive producer exits nonzero. Neutralize only the creating operator's inherited table/sequence/function/type/schema defaults within the same transaction, then restore archive defaults. Preserve bounded streaming, role checks and explicit recovery limits. Update stale writer-surface assertions to include the three pattern writers. Independently review the complete added security/restore slice; rerun full verification on a frozen revision. No production restore is included.

The full run at `73ddd02` ended **exit 1: 1,965 passed, 3 failed, 1 skipped,
1 warning**. Two failures are stale writer-surface expectations. The third
revealed existing default-ACL amplification during in-place restore, reproduced
with the two-test restore/dashboard sequence and an explicit all-relation ACL
comparison. These failures supersede the earlier pending-run status and are
not accepted as full-suite evidence.

The additional independent review of `73ddd02..c3df902` found two Medium
corrections: an embedded large-object COMMIT and inherited function EXECUTE
grants. The coordinator reproduced both with new regression tests before
fixing them. Large-object archives now require empty-target recovery and are
refused before any target connection; default resetting covers all five
PostgreSQL17 object classes. The prior full run at `c3df902` was interrupted
(exit 2, 356 passed, 1 warning) to avoid finishing an obsolete source revision.
It remains retained evidence, not acceptance. Focused correction checks are
coordinator-owned; the complete independent bounded review is retained.

### Slice S7: Isolate the legacy mining migration fixture

- [ ] T065-016 [AC-009, IC-004] Run the historical008→009 migration test in an owned isolated database containing exactly the first eight migrations. Preserve its queue-row and idempotency assertions; stop dropping/recreating `mining_batches` in the shared current schema, where later RLS belongs. Reproduce the migration-test→dashboard failure before the change, then verify both together and run final complete verification. This is a coordinator-reviewed test-only correction; production/SQL behavior is unchanged.

The frozen full run at `bfeedf0` returned exit1:1,973passed/1failed/1skipped/
1knownwarning, with355sourcehashes unchanged. The one failing dashboard test
found `mining_batches` without RLS or service policies after the historical
migration test. All restore checks passed; no new product defect was found.
The exact two-test sequence reproduced1pass/1fail. These results remain
retained and are not full-suite acceptance.
