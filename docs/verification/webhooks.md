---
title: Signed webhook verification
type: reference
doc_id: webhook-verification
readers: [maintainer, installation-operator]
status: verified
version: 0.6.29
depends_on: [webhooks]
assets: []
summary: Bounded synthetic webhook, upgrade and recovery evidence; no production destination is configured.
---

# Signed webhook verification

Issue [72](https://github.com/phense/agentic-rag/issues/72) targets 0.6.29/schema038.
The corrected runtime is frozen at `128d2cf`, based on the real
0.6.28/schema037 release `7669284`. These are bounded correctness and compatibility observations,
not a delivery SLA, production receiver test or merge approval. Independent
correction review accepted the code with C0/H0/M0/Low0. Its remaining playbook
finding was corrected and rehearsed separately. The one full run and its
mechanical test-only correction are recorded below.

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

## Review corrections and current focused evidence

The complete review at `18e9fd7` reproduced a canonical multi-document quota
lock cycle (IR072-001, High) and unreachable audited terminal retirement
(IR072-002, Medium; PB Important). The old100-test pass is historical and does
not prove those defects absent. The exact deadlock and missing cancellation
failed at `41ac41d`. A further red case at `69f826b` demonstrated an early
constraint/fanout quota gap; the corrected delivery admission closes it.

At `128d2cf`, the final focused selection passed **157 tests**, Exit0,223.56s
pytest time, with one existing Starlette/httpx warning. All457 recorded input
hashes match. It includes deterministic multi-document and edge/memory ordering,
record/byte/subscription quotas under READ COMMITTED and REPEATABLE READ,
actual mining/lifecycle, audit rollback, cancellation/retention, queue/fence
integration and archived028/restricted-owner restores. This is not a full suite.
The earlier matrix's two failures were oversized test-project fixtures rejected
before their quota assertions; corrected fixtures subsequently passed.

## Real CLI and bundled receiver

On 2026-11-04, the coordinator ran **47 actual CLI commands** on `128d2cf`
against an owned synthetic PostgreSQL17 database and the bundled loopback
receiver. There were45 successful commands and2 expected denials. Every
recorded source hash remained unchanged throughout this corrected rehearsal.
The earlier30-command run is retained separately; its whole-tree identity was
false because unrelated prose changed, and it is not relabeled unchanged.

| Workflow | Before → observed result | Wall time |
|---|---|---|
| Default off | One ordinary save →0 captured notices,0 sends |5.842s |
| Signed committed notices | Enablement +test +save →2 captured/2 acknowledged;53 canonical table hashes unchanged by delivery |7.696s |
| Receiver outage/replay | One path failure →retained attempt, successful due retry and explicit replay with unchanged event ID |16.255s |
| Rotation/off/retention | New key identity accepted; off →0 sends,4 retained deliveries |22.864s |
| Capacity recovery | Capacity failure rolls back; wrong terminal state refused; one cancellation/audit; repeat preserves retention; immediate prune0; simulated8-day aging permits prune1 delivery/1 event; subsequent capture acknowledged |31.638s |

The retention probe advances timestamps only in its owned synthetic fixture;
the operator command does not shorten the seven-day production retention.
Times include Python CLI startup and local database/HTTP work, not throughput
or an operational SLA. Separate receiver controls rejected tampering/stale
signatures, deduplicated and withheld an older resource version. The original
nine receiver checks remain applicable because its code is unchanged. No model
inference or external HTTP service was used; owned database, receiver and private
files were removed after the run.

The integration tests additionally cover current credential revocation before
the socket, foreign/read-only refusals, management/result rollback after process
death, both stale completion branches, quota rollback, malformed destinations,
mixed/private/mapped DNS answers, redirect refusal, proxy independence and
bounded response framing. Public HTTPS TLS/SNI behavior uses controlled socket
seams; no public receiver or certificate authority was contacted.

## Full run and release checks

On `86777cd`, the single full command
`python -m pytest -q --tb=short -p no:cacheprovider --durations=20` finished
with **2803 passed,12 skipped,1 failed**, Exit1,3568.99s, and one existing
Starlette/httpx warning. All1457 captured input hashes remained unchanged.
Log SHA256: `d1b2f4502b9462ae688b5da6debbf3803b4b52ab12841962658ef5dfd202ec65`.
This run is not relabeled a full-suite pass.

The sole failure was `tests/test_backup.py::test_restore_roundtrip`: its ACL
comparison passed `pg_class.relkind='S'` to `acldefault`, whose sequence argument
is lowercase`s`. An owned fresh-store reproduction confirmed that actual
SELECT/UPDATE/USAGE privileges and all normalized/default ACLs were preserved;
the old comparison alone failed after PostgreSQL normalized ACL storage.
Only the test helper's type argument and explanatory comment changed. The same
owned fresh restore then passed, and `python -m pytest -q tests/test_backup.py`
passed **18 tests**, Exit0,19.25s. No assertion was removed or relaxed; the
comparison now includes all sequence-owner privileges. Runtime and SQL remain
byte-identical to the full run and independently accepted correction. The
mechanical two-line change was reviewed by the coordinator. In accordance with
the maintainer's test-cost policy, the complete suite was not repeated.

Node7, documentation17, lock and wheel checks passed; the wheel contains38 SQL
files and155 Python modules byte-equal to the corrected runtime. These checks
overlap with other selections and are not added into a unique-test total.

## Open gates and operation boundary

IR072-001/002 and PB072-IR-001 are resolved by the independent correction review.
PB072-CR-001 identified that normal scoped status cannot inspect a remote-owned
subscription as a local operator. Its correction adds only an explicit READ ONLY
owner metadata inventory; remote permissions and runtime code are unchanged.
The coordinator executed the exact printed Python block after real synthetic
credential revocation: local status still404; the inventory found the revoked
delivery; ordinary named CLI cancellation produced one audit; repeating it kept
the same retention; immediate prune remained0. All59 table hashes were unchanged
by each inventory call, and no body, endpoint or credential was printed. Cursor
filtering and invalid-ID refusal also passed; the owned database was removed.
The initial snippet-extraction harness failed before opening a database because
it did not handle indented Markdown fences; the corrected harness passed.

CI, merge and both populated production upgrades remain open.
No keys, subscriptions, endpoints
or sender daemon have been configured on either production host.
