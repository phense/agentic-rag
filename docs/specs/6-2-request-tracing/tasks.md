# Tasks: bounded request and job tracing

Feature `RAG-060`; inputs `spec.md`, `plan.md`, `docs/uml/findings.md`.

## Architecture findings

AF-060-01 current-scope SQL filtering; AF-060-02 immutable durable origin; AF-060-03 bounded best-effort failure. Implementation owns all application/test changes; coordinator owns documentation and release metadata.

## Implementation slices

### Slice S1: Durable metadata and authorized diagnostics

- [x] T001 [AC-001..007] Observe meaningful red tests for metadata/redaction/scope/origin/retention/failure; files tests/service/test_tracing*.py; catches leaks, false enqueue completion, origin loss and unbounded logs.
- [x] T002 [AF-060-01..03] Add026 owner-only metadata/origin fields and guarded schema/upgrade support; files sql/026_request_tracing.sql, service/schema.py, service/upgrade.py; depends T001.
- [x] T003 [IC-001/002] Instrument Gateway/Dashboard/MCP and accepted job origins without payload capture; files service/tracing.py, api.py, dashboard.py, ingest.py, requests.py; depends T002.
- [x] T004 [IC-003] Implement scoped bounded listing/detail/export, REST/CLI/dashboard UI and live-job status; files service/tracing.py, operator.py, dashboard_views.py, dashboard_assets/app.js, tests/browser/; depends T003.
- [x] T005 [AC-007] Verify targeted tests, redaction, upgrade originals/restore/retry and bounded concurrency/overhead; depends T004. Report exact commands/exits and2–3 measured examples.

### Slice S2: Reconcile and verify integrated behavior

- [x] T006 Coordinator reconciles as-built sequence, derives real success/recovery integration tests with independent reviewer, exercises AC-001..007; depends T005.
- [x] T007 Coordinator authors/reviews PB-060, bumps four release files0.6.13, records source/measurement limits; depends T005.
- [x] T008 Independent complete bounded diff review; fix all Critical/High/Medium with regressions, repeat if integration/security materially changes. Low findings in confirmed canonical bucket; depends T006/T007.

### Slice S3: Convergence and final verification handoff

- [x] T009 Reconcile requirements, tasks, findings and actual checks; run fresh full suite plus browser/Node/package/version checks; depends T008.
- [ ] T010 Create focused PR linked60, link to thread immediately, report status2/15 and wait for maintainer. Do not merge without their response; depends T009.

## Dependencies and parallelism

S1 precedes S2/S3. Coordinator documentation may proceed alongside application ownership; test database use serialized. No parallel application writers. PB-060 ready/reviewed before delivery, isolated upgrade procedure ready before rehearsal. No production rollout.

T010 is the external publication/approval handoff. This pre-publication snapshot
keeps it open; GitHub records the actual PR and subsequent merge decision.
