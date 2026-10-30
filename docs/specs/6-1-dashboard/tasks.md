# Tasks: Authenticated dashboard

## Stable work ID

RAG-059; [spec](spec.md), [plan](plan.md), [model](../../uml/dashboard.md).

## Architecture findings

AF-059-01→T059-02; AF-059-02→T059-01; AF-059-03→T059-03. Coordinator owns all implementation paths; no parallel mutable ownership.

## Implementation slices

### S05901: Browser and administrative authority

- [x] T059-01 [US001/AC001–002/AF05902] Write and observe failing bootstrap/race/session/origin/CSRF tests, then implement isolated bounded browser boundary, CLI arming and session reuse in `service/dashboard.py`, `service/operator.py`, `tests/service/test_dashboard.py`.
- [x] T059-02 [US003/AC005/AF05901] After01, red-first explicit validated preview/apply, policy revision/last-admin/race protections, prepared journal/crash reconciliation and once-only secrets in `service/dashboard_policy.py`, SQL025 and dedicated tests. Extend upgrade/restore contract.

### S05902: Setup and scoped operations

- [x] T059-03 [US002/003/004/AC003–007/AF05903] After01/02, red-first resumable modes/checks/idempotent completion, bounded presence and RLS projections; implement packaged responsive accessible assets, scoped search/source/review queue and admin inventory.
- [x] T059-04 [AC008–009] After03, verify browser desktop/mobile/keyboard, permission changes, expiry/revocation/restart and40-user resource behavior. Add synthetic and populated024→025 strict backup/restore/retry proof; no production mutation.

Progress on T059-04: four final real-browser flows pass (33.55s); 024→025 copy restore/upgrade preserves301,183 original rows in28 tables. Forty-session cold and warm read soaks complete. Actual owned-API process restart preserves setup and all5 live checks. Corrected40-session soaks each complete2,400 reads with unchanged database allocation/max6 connections. Third whole-feature review is complete with0 C/H/M/feature Low and158 passing checks. Final full suite passes 1,569 tests (1 intentional Linux skip); final documentation synchronization is recorded separately with the owned-copy deployment receipt.

### S05903: Integration and delivery

- [x] T059-05 After04, reconcile as-built model; independent Sol high whole-feature reviewer derives success and recovery scenarios. Run them against real components and fix C/H/M. Minimum1 maximum3major review rounds; small finding fixes coordinator-owned. Low findings inIssue75.
- [x] T059-06 After05, PB05901/02 content/rehearsal, docs set updates, feature inventory,0.6.12 metadata, wheel/assets, full serial Python and affected host checks. Hetzner copy-only deploy/probes with protected private evidence. Capture2–3numeric before/after examples and exact limits.
- [x] T059-07 After06, converge requirements/contracts/review/evidence, create and link tested PR against current stack target, leave merge/canonical rollout approval separate.

## Tests

API/security/administrative tests in `tests/service`; browser harness under `tests/browser`; migration tests extend `tests/service/test_upgrade.py`; full `pytest -q -p no:cacheprovider` on ownedPG55458. Each red-first test protects observable issue behavior, no implementation-mirroring tests. No concurrent root fixtures. Exact command/exit artifacts in verification record.

## Dependencies and playbooks

01→02→03→04→05→06→07. PB05901/02 author/content review/owned-copy rehearsal areT05906 delivery blockers; PB058 upgrade/restore reuse isT05904. No parallel-safe work required. Convergence may append coordinator fix tasks within this work ID rather than launch a new lifecycle.

Delivery: [PR79](https://github.com/phense/agentic-rag/pull/79), stacked on PR78.
All implementation/convergence tasks are complete; merge and canonical rollout
remain separate maintainer actions. Final documentation-only synchronization
uses the existing owned-copy deployment receipt without restarting runtime.
