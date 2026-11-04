---
title: Signed webhook verification
type: reference
doc_id: webhook-verification
readers: [maintainer, installation-operator]
status: draft
version: 0.6.29
depends_on: [webhooks]
assets: []
summary: Bounded synthetic webhook, upgrade and recovery evidence; no production destination is configured.
---

# Signed webhook verification

Issue [72](https://github.com/phense/agentic-rag/issues/72) targets 0.6.29/schema038.
The implementation is frozen at `2d42176`, based on the real 0.6.28/schema037
release `7669284`. These are bounded correctness and compatibility observations,
not a delivery SLA, production receiver test or merge approval. Independent
complete review has found two blocking defects described below; the final full
suite has not run.

## Focused checks and compatibility

The implementation first froze the failing default-off/capture contract at
`f227bb3`. Two further regression tests were frozen at `260c01e`: concurrent
capture/subscription mutation lock order and a direct writer RPC omitting its
optimistic revision. Both failed before the SQL correction.

The broad focused selection passed 260 tests in 319.52s. After the final SQL lock
correction, the relevant 100-test selection passed in 127.87s; its 456 recorded
runtime/SQL/test/release input hashes match the final implementation. These
selections overlap and are not 360 unique tests. Each has one pre-existing
Starlette/httpx deprecation warning. The final selection covers webhook capture,
delivery, archived upgrade, queued atomicity, final authority and research-tool
inventories. Neither selection is the full suite.

An actual archived 0.6.28 package, rather than newly written source-version
fixtures, seeded 76 original rows across 54 tables. The 038 rehearsal checked:

- An interrupted migration exits 9 before commit; retry applies 038 once.
- Independent source and target restores preserve original rows, ACLs, owners,
  sequences, vectors, pins and pending work.
- Two old scoped readers and an old 028 writer continue working. With capture
  explicitly enabled, that old writer also creates a durable delivery intent.
- An independently restored target retains one pending intent.
- A restricted deployment owner remains NOSUPERUSER/NOBYPASSRLS; the documented
  prepared vector template supports its installation and backup restores.

Published migrations 001–037 are byte-identical to `7669284`. The sequence ACL
inventory now uses PostgreSQL's sequence default-ACL kind `s`; exact restores
still compare every original sequence privilege. Preservation comparisons allow
the new additive sequence without exempting original sequences from comparison.

## Real CLI and bundled receiver

On 2026-11-04, the coordinator ran 30 actual CLI commands against an owned,
synthetic PostgreSQL 17 database and the bundled loopback HTTP receiver. The
runtime, SQL, tested procedure, receiver and rehearsal-script hashes remained
unchanged. README/feature-summary prose changed during the run, so the original
whole-tree `sources_unchanged` flag is false; a separate identity reconciliation
records those documentation-only differences. No whole-tree-unchanged claim is
made for this run.

| Workflow | Before → observed result | Wall time |
|---|---|---|
| Default off | One ordinary save → 0 captured notices,0 sends | 4.575s |
| Signed committed notices | Explicit enablement + test + save → 2 captured and 2 acknowledged notices; 53 canonical table hashes unchanged by delivery | 6.812s |
| Receiver outage/replay | One path failure → retained failed attempt, successful due retry and one explicit replay with the same event ID | 17.428s |
| Rotation/off/retention | New key identity accepted; switch off → 0 further sends and 4 retained delivery records | 21.973s |

Times include separate Python CLI startups and local database/HTTP work. They do
not measure production throughput or the multi-hour retry schedule. Separate
receiver controls accepted duplicates without repeating work, rejected a
tampered body and stale timestamp, and retained an older resource version as
seen without replacing the current version. Nine direct example checks also
passed, including deduplication after receiver restart and private-store mode.
No model/provider or external HTTP service was called. The receiver, owned
database and private test files were removed after the run.

The integration tests additionally cover current credential revocation before
the socket, foreign/read-only refusals, management/result rollback after process
death, both stale completion branches, quota rollback, malformed destinations,
mixed/private/mapped DNS answers, redirect refusal, proxy independence and
bounded response framing. Public HTTPS TLS/SNI behavior uses controlled socket
seams; no public receiver or certificate authority was contacted.

## Open gates and operation boundary

The complete review at `18e9fd7` confirmed a multi-document deadlock between
the quota lock and a later canonical document lock (IR072-001, High). It also
confirmed that permanently withheld deliveries have no audited retirement path
and can exhaust capture capacity (IR072-002, Medium; PB Important). Both are
being corrected with targeted red/green tests and fresh procedure rehearsal;
the earlier focused passes do not establish readiness. Independent code/security/upgrade and
[PB07201](../webhooks.md) review, final full-suite output, release checks, CI,
merge and both production upgrades remain open. No keys, subscriptions, public
endpoints or sender daemon have been configured on either production host.
