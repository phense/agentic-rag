# Change Tasks: Statement-local document permission inputs

## Stable work ID

- Change ID: `document-permission-initplans`; parent RAG-092 / #92 and #68.
- Proposal: [proposal.md](proposal.md).
- Executor: coordinator; serial shared-state tests, no parallel database mutations.

## Tests

- [ ] C001 Freeze the 021 policy fixture; characterize role/settings/read/write/nested and error parity, full-scope generic-plan revocation and point paths. Observe a failing once-per-statement plan-work test before 035. Catches missing admin EXECUTE, eager JSON parsing, stale prepared permissions and non-inlining.

## Implementation

- [ ] C002 Add only migration 035's pure helper and document-policy expressions; qualify the operator, explicitly retain PUBLIC EXECUTE and every existing role. Preserve 001–034. Depends C001.
- [ ] C003 Pass parity, lazy evaluation, shadowing/inlining and live revocation checks; retain test evidence for the actual baseline and current expressions. Depends C002.
- [ ] C004 Extend populated 0.6.21 upgrade/retry/source+target independent restore and limited-owner tests; prove rollback/reapply and original-row/queued-work invariants. Reconcile migration-count assertions without weakening them. Depends C003.
- [ ] C005 Independently review the complete RLS/migration/upgrade diff; resolve C/H/M and record Low. Depends C004.
- [ ] C006 Freeze and run the fresh effectiveness benchmark under the prospective design gate; any invalid or ineffective run stops delivery. Depends C005.

## Delivery and playbook

- [ ] C007 Update PB06801 and sidecar for schema035, compatible clients, verified upgrade, rollback/reapply and failed-gate actions; independent content review and populated rehearsal before delivery. Depends C004.
- [ ] C008 Fresh affected/full/Node/build/lock verification on the final tree; then exactly one newly frozen parent actual-client physical run with unchanged gates. Depends C005–C007.
- [ ] C009 Reconcile parent tasks and both Issues using terminal evidence. Physical FAIL leaves them open and requires user decision for standalone shipping. No production rollout. Depends C008.
- [ ] C010 Synchronize accepted requirement deltas and archive only after every specified task is complete, review accepted and fresh verification passes.
