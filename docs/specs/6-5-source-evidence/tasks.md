# Tasks: Consistent source evidence and review state

## Stable work ID

Feature `6.5`; work `RAG-063`; Issue63; [specification](spec.md), [plan](plan.md); artifact `docs/specs/6-5-source-evidence/tasks.md`.

## Architecture findings

AF-063-001 concurrency/revisions→S1/S2; AF-063-002 authority/bounds/host metadata→S2/S3; AF-063-003 lifecycle/invalidation→S2/S4; AF-063-004 migration/recovery→S1/S4/S5. Canonical findings: `docs/uml/findings.md`.

## Tests

Test-first meaningful failures precede each new behavior. Keep exact red/green commands, exit status and source revision in the implementation report. Mock provider boundaries only, never the authority/SQL/transaction behavior being tested. Isolated PG55460 only; finite scratch in SHM.

## Implementation slices

### S1: Portable revisions and additive history

- [x] T063-001 [AC-003/004/008/009] [AF-063-001/004] Write and observe red tests for restore-stable revisions, legacy change/ABA invalidation and append-only scoped history; implement additive `sql/029_source_evidence.sql` and affected schema/upgrade acceptance. No original-row field rewrite/backfilled review; source0.6.15→0.6.16. Files: sql/029, service/schema.py, service/upgrade.py, tests. Evidence: migration baseline/hash/retry tests; no dependency.

### S2: Shared bounded evidence and audited CAS

- [x] T063-002 [US-001/003] [AF-063-002/003] Red→green a version1 evidence/history producer with exact quotes, opaque identities, event times, speaker/kind/completeness, separate lifecycle/trust/review, exclusion reasons and explicit legacy/manual origin. Whole-set tokens, finite pages, no technical host navigation. Files: evidence.py or evidence_contract.py, store.py, read_limits.py, tests; depends T063-001.
- [x] T063-003 [US-002] [AF-063-001/002] Red→green strict expected-version review/source-state gateway using canonical audited writes and current authority; preserve no-token legacy calls, atomically persist actual actor/reason/versions/history. Deterministic claim→source locks; stale/ABA/attachment/audit/revocation tests. Files: evidence.py/store.py/tests; depends T063-002.

### S3: Four client surfaces

- [x] T063-004 [IC-001..004] Red→green shared MCP/REST tool registration, structured conflict mapping, RO scope/bounded/non-oracular failures; preserve old calls. Files: mcp_server.py, service/engine.py/API/schema registries, service tests; depends T063-003.
- [x] T063-005 [US-001/002] Red→green local and central CLI evidence/history JSON and readable text plus strict version options, retaining legacy invocations. Files: cli.py, service/client.py if needed, CLI tests; depends T063-004.
- [x] T063-006 [US-001/002] Red→green dashboard evidence/history drilldown and version-bound audited review/source actions. Use safe text nodes, explicit uncertainty and refresh-after-conflict. No raw host provenance navigation. Files: dashboard_views.py/assets/app.js/style.css if needed, real browser tests; depends T063-004.

### S4: Integration, upgrade and user documentation

- [x] T063-007 [AC-007] [AF-063-003] Exercise real current search/context/profile/thematic/pattern paths after withdrawal/correction/expiry/supersession/revocation; fix confirmed stale acceptance through existing eligibility gates, not a second truth engine. Files: relevant consumers+behavior tests; depends T063-004..006.
- [x] T063-008 [AC-008/009] [AF-063-004] Rehearse representative populated028→029, verified backup restoration, original-field/ACL hashes, interrupted retry, actual prior-client reads and restore-stable evidence versions; retain executable harness/evidence. No production writes. Depends T063-001..007.
- [x] T063-009 [FR-005] Author PB-063-UPGRADE at `docs/playbooks/system/rag-063-source-evidence-upgrade.md` using authoring/playbook skills; update claim-evidence docs and measured examples/limits, patch0.6.16 pyproject/lock/badge/changelog. Record 2–3 actual numerical examples and source boundaries. Independent playbook review+rehearsal is a delivery dependency. Depends T063-008.

Implementation note (2026-10-31): T063-009 authoring and the implementer's isolated rehearsal are recorded in `docs/playbooks/system/rag-063-source-evidence-upgrade-review.md`; the independent playbook review remains part of T063-010.

## Dependencies

S1→S2→S3→S4; T063-005/006 are conceptually separate but executed sequentially by one owner because shared client fixtures and limits affect both. No parallel-safe writer marker. Implementation owner owns product/test/doc files; coordinator owns durable state, integration/review and publication. No agent reverts unrelated edits.

## Final integration

### S5: Coordinator-owned reconciliation and independent review

- [x] T063-010 Reconcile as-built `docs/uml/source-evidence-63.md` and findings with code/tests; disposition every difference. After reconciliation, a separate strong architect derives at least one collaborating-component success and one rollback/recovery test; execute both and record actual exits. Independent PB-063-UPGRADE content review plus required rehearsal must pass. Depends T063-009.
- [x] T063-011 Independent complete bounded base5390a6f→final diff review, including security/concurrency/upgrades and interface semantics. Verify/fix all C/H/M; re-review each changed range. Any nonblocking Low goes to Issue75. Depends T063-010.

### S6: Convergence and handoff

- [x] T063-012 Invoke speckit-converge; run fresh whole-suite, actual exit, Node syntax, wheel artifact/migration packaging and version/docs consistency on frozen final tree. Recheck main target version; publish one PR for63 after all required gates, link it immediately, update canonical issue, report step5/15 and await NEW weiter. Never merge this PR or update production as part of this task. Depends T063-011.

## Playbook obligations

PB-063-UPGRADE is a required system deliverable, owned by implementation T063-009; independent review/rehearsal accepted at T063-010 before delivery. Development operations: none involving live systems in this PR; isolated automatic migration tests only. Existing upgrade/recovery procedures are reused and adapted rather than multiplied.


Delivery record (2026-10-31): [PR84](https://github.com/phense/agentic-rag/pull/84)
is published and linked. Independent review and final whole-suite gates passed;
no open C/H/M/Important finding. Source/test/schema/assets are unchanged from
verified `2c92d4d`; subsequent commits record delivery only. Await NEW weiter for
this PR's merge approval; production deployment remains separate.
