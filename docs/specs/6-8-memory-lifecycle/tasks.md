# Tasks: Source-preserving consolidation and lifecycle views

## Stable work ID

Feature6.8 / RAG-066 / [Issue66](https://github.com/phense/agentic-rag/issues/66), roadmap8of15.
[Spec](spec.md), [plan](plan.md), [contract](contracts/lifecycle-v1.md),
[design](../../uml/memory-lifecycle-66.md). Baseline `d4d2372` (0.6.18/schema030);
target0.6.19/schema031. Planning-only commits do not establish implementation.

## Architecture findings

AF-066-001..010 in [findings](../../uml/findings.md) are design obligations, with
coordinator corrections explicitly superseding the original recommendations.
001: five classes/assertion+alias exclusions/legacy archive boundary;002: lv1/ev1;
003: flat groups/locks/replay/correction;004: all reader/view defaults before LIMIT;
005: derived invalidation;006: stale/target-failure rules;007: populated upgrade and
old code/worker policy;008: current authority/RO/non-disclosure;009: title/body/type
exact-auto proof;010: immutable base snapshots versus action ABA. No finding is
waived by generating tasks; resolve with implementation and evidence.

## Tests and resources

Exactly one pytest process. Existing owned PostgreSQL17/pgvector on PG55460,
never5432. `TMPDIR=/dev/shm/rag66-20261031-tests`, `PYTHONDONTWRITEBYTECODE=1`.
Mock only external provider boundaries; no new providers/model downloads/private
corpus or production operations. The baseline command was
`.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider tests/test_curation.py tests/test_validity.py tests/test_domain_assertions.py tests/test_evidence_invalidation.py`:
42 passed, exit0,22.90s atd4d2372. Final parent suite had1974 passed/1skip/1warning.
Record actual reds before new behavior, not manufactured later. New tables/fixtures
use owned random databases or the approved fixed test fixture only under PG55460;
never mutate another suite's schema or another run's resources.

## Implementation slices

### Slice S1: Bounded reversible consolidation, current views and populated upgrades

One serialized implementation owner for the complete coupled feature. No parallel
product writers or independently mutable interface assumptions.

- [x] T066-001 [AC-001/002/005/006/010; AF-001/006/009/010] Freeze hand-labelled synthetic exact/richer/contradictory/different-entity/cross-scope/delayed-import/ABA fixtures and expected view outcomes before product edits. Include differently titled identical bodies as automatic non-merge, qualified/unqualified evidence, immutable assertion replacements and old archived duplicates. Files: new `docs/benchmarks/2026-10-31-memory-lifecycle/fixtures/`, loader and hashes. Evidence: fixture-first commit and hand-inspected expected outcomes; no model quality claim.
- [x] T066-002 [AC-003/005/006/008; IC-002/003; AF-002/003/004/005/010] Observe meaningful schema/security/eligibility reds, then add `sql/031_memory_lifecycle.sql`: empty additive decision/event overlay, UUID event paging, immutable identity/append-only audit history, exact grants/RLS/UPDATE guard, flat canonical uniqueness/cycle guard, portable lv1/base-snapshot helpers and view-aware same-signature assertion eligibility. Retain the exact030 base; leave001..030 and ev1/src1 unchanged. Guard privileges/search_path and deterministic lock protocol must be explicit, not inferred from RLS. Extend schema checks only as needed. Evidence: PostgreSQL constraints, no foreign rows/default ACL leaks, untouched-original/version equality, replacement persistence and no view bypass of patterns.
- [x] T066-003 [AC-001/002; IC-001; AF-001/009] Test then implement pure bounded preview/classification and anchored source/event explanations in new `agentic_rag/lifecycle.py`. Distinguish proof from operator judgement and all five operation types. Tighten existing exact automatic curation to identical title/body/dtype plus existing scope/evidence restrictions. Preserve its archive/edge/audit behavior for justified copies; do not add a semantic automatic worker. Evidence: no writes/provider calls, missing/foreign parity, false entity/non-merge fixtures, genuine duplicate green cases and honest false-negative count.
- [x] T066-004 [AC-003/005/006/008; IC-002; AF-003/006/008/010] Test then implement thin store gateway apply/correct with ordered anchor locks, bounded lock/statement times, semantic replay keys, expected lv1/decision versions, current commit-authority checks and atomic decision/event/audit writes. Base snapshots exclude action event counts, so application and sibling members do not stale themselves. Corrections never restore source/status/truth fields. Evidence: opposing concurrent merges, chain attempts, two members, replay across request IDs, mismatch, action/source ABA, stale preview, audit failure, revoked principal and lock recovery; actual all-or-nothing rows and cleanup.
- [x] T066-005 [AC-004/006/007; IC-003; AF-004/005/006] Test then wire optional explicit current/latest/include_merged/historical selection across search/indexes/identity/graph/research/get with one view context that opens a transaction where needed and restores prior settings. Preserve omitted payload/default contracts; include_merged never revives replacements, explicit historical enforces qualified past trust/time while legacy history keeps its old semantics. Integrate profile lifecycle token, thematic stale behavior and view-independent pattern withholding. Detail/history explains immutable assertions and legacy archived duplicates without moving evidence. Evidence: k=1 pre-LIMIT selection per candidate family, nested/savepoint/autocommit setting leaks, invalid-view combinations, canonical unavailable/non-oracular labels, stale source/status/scope transitions, replacement target purge and all relevant derived readers.
- [x] T066-006 [AC-001/004/008; IC-001/002/003; AF-008] Expose pure preview/detail/history and writer-only apply/correct across local MCP, server MCP, REST and local/client CLI using shared registration/engine/gateway. Optional view fields are omitted over old-server wire when unset. Add bounded pagination, error mapping and tool-reference docs. Evidence: real authenticated transport parity, writer/RO/foreign/revoked identities, no foreign identifiers/counts, client old-server ordinary-call compatibility and explicit new-view rejection.
- [x] T066-007 [AC-003/009; IC-004; AF-007/009] Rehearse populated0.6.18/schema030→0.6.19/schema031 using actual archived `d4d2372` code and owned multi-user/multi-domain fixtures. Add0.6.18 source support and031 restore-resume/schema allowlists. Prove original rows/sources/grants/owners/pins/queues/history and ev1/src1 unchanged, zero automatic decisions/provider calls, interrupted/empty retry, verified backup and independently restored copy. Run actual old readers/get/history/ordinary writes before/after decisions; test old curation policy limits and safe old-code fallback with curation_budget=0. Required worker/hook inventory/update/restart and post-backup-write loss limits go into PB-066-OPS. No live rollout.
- [x] T066-008 [AC-010; FR-005; PB-066-OPS] Run three reproducible deterministic fixture repetitions on clean identified product source; inspect2–3 actual scenarios and publish false merges/non-merges, source retention, retrieval labels/changes, actual timing/calls/budgets/concurrency outcomes and exact limits. Deliver user guide, config/CLI/MCP references, V-066, PB-066-OPS and executable owned-copy rehearsal of upgrade/preview/apply/correct/failure/recovery through public CLI/REST. Use writing/playbook skills; exact+1 version0.6.19 in pyproject/uv.lock/README/CHANGELOG. Keep prior frozen feature fixtures/measurements and #21 unchanged.
- [x] T066-009 Run all new/affected suites serially after final changes, including real transport/upgrade and affected evidence/profile/thematic/synthesis/curation behavior. Inspect actual exits; commit a clean coherent S1 handoff, record source revisions/red-green evidence/changed files and any unresolved limits. Owner writes ignored `.engineering-method/runs/RAG-066/s1-implementation.md`; no task checkboxes/state/GitHub/PR/deployment or full-suite claim. Coordinator verifies the handoff before accepting tasks.

## Dependencies

| Work | Depends on | Reason | Parallel-safe |
|---|---|---|---|
| T066-002/003 |001 | Frozen expectations before product | None |
| T066-004 |002/003 | Shared schema/classifier/version rules | None |
| T066-005/006 |004 | Current state, authority and correction contract | None |
| T066-007 |002..006 | Actual integrated upgrade/client behavior | None |
| T066-008/009 |007 | Final measurement, public recovery and proof | None |

## Final integration

### Slice S2: As-built architecture, independent review and recovery gates

- [x] T066-010 Coordinator inspects actual S1 report/commits/exits and full base-to-head diff; reconciles all AC/IC/AF obligations and as-built model against code, preserving justified design changes. Route concrete gaps into the same executor; do not call a running/failed suite passed.
- [x] T066-011 Independent strong reviewer checks complete bounded feature diff, schema/RLS/auth/concurrency/source preservation/view defaults and PB-066-OPS content/rehearsal. Derive a probe plan before running owned collaborating-component ACF-066-S success and ACF-066-R audit/revocation/concurrent/correction recovery flows, with original-row and source-version proof. No product/state/GitHub edits by reviewer. Coordinator personally fixes small findings; use risk-proportionate new review only for material changed boundaries. Fix all Critical/High/Medium; collect Low in Issue75.

### Slice S3: Convergence, final verification, PR and autonomous merge

- [x] T066-012 Run speckit-converge and resolve every actionable gap through this executor. Run source-bound full pytest and relevant Node suites, inspect actual exit/failure/warning/skip output, offline wheel SQL/assets/import/version smoke, uv lock, relative links and exact patch bump against current target main. Retain failed/interrupted evidence; independent review and targeted tests do not stand in for full acceptance.
- [ ] T066-013 Synchronize Issue66, BACKLOG/FEATURES and public evidence, create focused PR closing66 with tested upgrade/recovery and2–3 measured examples, link it immediately to this thread after creation and each push. Verify exact head/base/current checks/reviews; merge autonomously under the maintainer's explicit remaining6.x permission only when gates pass. If waiting for checks, watch PR and end the turn; do not poll. Report PR/merge/step8of15 briefly, then continue67; no production rollout implied.

## Coverage and playbook obligations

AC-001→001/003/006;002→001/003;003→002/004/007;004→005/006;
005→001/002/004;006→001/002/004/005;007→005;008→002/004/006;
009→007;010→001/008. IC-001→003/006;002→002/004;003→005/006;
004→007. AF001→001/003;002→002;003→002/004;004→002/005;
005→002/005;006→001/004/005;007→007;008→002/004/006;
009→001/003/007;010→001/002/004. All checked again at010/011/012.

PB-066-OPS at `docs/playbooks/system/rag-066-memory-lifecycle.md`: authoring and
public-command owned-copy rehearsal in008, independent content review in011,
final current-evidence check in012. Both content and execution must pass before013.
No separate development-operation playbook because no development production or
manual destructive operation is authorized; existing isolated fixtures own cleanup.

## Executor evidence at the S1/S2 handoff (2026-11-01)

Fixture-first b0f3bf5 precedes product8fc8e9c;001..030 and frozen fixture bytes
are unchanged. S1 ends at40b8b31, source tests at351b6f4:1188 passed/exit0;
17 docs checks after the documentation-only commit. Root inspected the source,
actual log and current Git/Issue state; baseline main remainsd4d2372. Root then
reproduced two Medium view defects with4 failing cases and fixed them in82c031f;
19 view/transport tests passed/exit0. As-built contract/model now match these
seams, with explicit unresolved review questions. TDD process departures in S1
(registration/upgrade structural reds and some tests written after code) remain
disclosed in the handoff and V-066; no retrospective behavioral-red claim.

T066-011 and012 are open. The S1 implementation report is not an independent
review or full-suite pass. Source-bound complete verification, raw-SQL scope
visibility, request-key parity, public history paging and managed-index k=1
remain review/final-gate obligations; task acceptance above is implementation
and as-built handoff only. No production operations or GitHub PR have occurred.

Final verification at4a7f925: full2063passed/1skip/1knownwarning,exit0,371sources
unchanged; independent corrections accepted(noCHM/Important),50assertions48pass
2deferredLow. Populated227rows45tables/versions/ACLs/retry/restore/PB preserved;
three identical frozen measurements plus seven paired security-cost rounds.
Node7,lock55,wheel182payloadmatch,docs17,255relative links valid. Post-run
changes are documentation and benchmark evidence only. T066-013 remains open
until actual PR/CI/merge; no production rollout is inferred.
