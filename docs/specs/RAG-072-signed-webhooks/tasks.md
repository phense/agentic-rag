# Tasks: Reliable scoped webhooks

## Ownership and execution boundary

Root owns spec/plan/tasks/UML, documentation, state and integration acceptance.
One implementation writer owns runtime/SQL/tests/release labels. Execute only
after the independent design gate is reconciled. No production receivers or
subscriptions, no overlapping file writers, no new framework or model calls.

### S072-1: Transactional scoped event contracts

- [x] T072-001: Freeze meaningful red tests for default-off capture, committed
  versus rolled-back writes, exact scopes, idempotency/revision, read-only and
  foreign denial, current revocation, bounded storage and audited atomicity.
  AC-001..003/005; AF072-001/002/006.
- [x] T072-002: Implement additive038 capture/control/subscriptions/outbox and
  lease metadata with safe ACLs/RLS/definer boundaries, field/size bounds and
  schema checks. Cover documents, reviews, source changes, actual lifecycle
  events and owned terminal ingestion receipts. Preserve001..037 exactly.
- [x] T072-003: Implement scoped gateway management/status/replay/test/rotation
  without clearing queued transaction or execution authority. Local operator
  controls capture and private key export. Audit and optimistic revisions are
  atomic; no signing secret enters a request spool or normal tool result.
  Dependencies:T072-001/002; IC-001/002/004; AF072-002/003.

### S072-2: Separate delivery and compatibility

- [x] T072-004: Red tests then bounded explicit sender: fenced leases, current
  access recheck, exact-byte signature, distinct key generations, crash retries,
  duplicate/out-of-order receiver behavior, timeout/backoff/dead letters and
  retention. No network in canonical transactions. AF072-003/005/006.
- [x] T072-005: Pinned public HTTPS transport and explicit operator-only private
  origin/CIDR policy; test mixed/rebound DNS, redirects, proxies, metadata,
  malformed URLs and bounded responses without contacting private services.
  IC-003; AC-006; AF072-004.
- [x] T072-006: Local/remote CLI and MCP/REST adapters with exact read/write tool
  inventories and sanitized errors. Add exactly029 project/lock/badge/changelog
  and current/future supported-version references. Reuse normal authentication
  and budgets; do not broaden existing read-only operations.
- [x] T072-007: Archived028 representative populated upgrade: interrupt/retry,
  source and target independent restore, restricted owner, old readers/writer,
  unchanged originals/ACLs/owners/sequences/vectors/pin/pending work and safe
  code rollback with retained038 metadata. AF072-001/006; AC-008.
- [x] T072-008: Focused relevant integration checks, exact input/log/exit
  evidence, cleanup own isolated databases/processes; no full suite yet.

### S072-2C: Confirmed review corrections

- [ ] T072-C01: Freeze the exact canonical multi-document deadlock regression;
  defer hard quota/order finalization, preserve capture-time scope/state, prove
  READ COMMITTED/REPEATABLE READ quota and mixed edge/memory ordering, real
  mining/lifecycle and archived028 behavior. IR072-001.
- [ ] T072-C02: Local audited named terminal cancellation with expected state,
  lease fencing, unchanged retention on repeat and no live-work deletion.
  Rehearse seven-day prune and capacity recovery. IR072-002/PB072-IR-001.
- [ ] T072-C03: Independently review the complete correction boundary; retain
  unchanged accepted evidence and resolve new C/H/M/Important before full/PR.

### S072-3: Acceptance and delivery

- [ ] T072-009: PB07201 `docs/webhooks.md`, executable local receiver/signature
  verifier, opt-in, secret export/rotation, scope, outage/replay/capacity,
  archived028 upgrade and safe rollback. Root rehearses real CLI/receiver with
  synthetic content and reports2–3 measured before/after examples.
- [ ] T072-010: Reconcile as-built architecture; derive and execute ACF072-S/R/U.
  Independent complete bounded security/concurrency/upgrade and playbook review;
  resolve C/H/M/Important, track nonblocking Low separately without reopening
  unchanged inherited work. Review fixes proportionately.
- [ ] T072-011: One full suite near PR on final runtime inputs, relevant lock,
  wheel/SQL and existing Node checks; observe terminal results. No repeated full
  runs for unchanged inputs or mechanical inventory/documentation fixes.
- [ ] T072-012: Focused PR, CI, merge under current autonomy; separately verify
  both populated production upgrades/restores with capture off and no receiver,
  preserve rollback proof, close canonical72 only after verified delivery.
