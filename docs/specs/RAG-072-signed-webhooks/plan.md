# Implementation Plan: Reliable scoped webhooks

## Stable work ID

RAG-072; [specification](spec.md); source7669284,0.6.28/schema037;
target0.6.29/schema038. No production receivers are in scope.

## Summary and repository evidence

Use database triggers to record minimal change events in the same transaction
as canonical writes. This covers retained0.6.28 clients and avoids trying to
reconstruct committed changes from mutable text audit summaries. Keep all
delivery and key material in an explicit separate operator sender. Existing
CLI/MCP dispatch and REST `/v1/tools` provide scoped subscription management.

`store.py` already updates documents, chunks, edges and audit in one transaction;
`evidence.py` controls source/review writes. SQL022 owns service ingestion
receipts with namespace/project. SQL029..030 supply versioned evidence. The
existing `service.context` and `auth.resolve_reference` enforce current rights;
`service.queued_transaction` and `fence` own receipt/execution atomicity. Preserve
those boundaries. No third-party broker, database cache or pooling is needed.

## Project gates

| Gate | Response |
|---|---|
| Sequential numbered requests | #71 merged/deployed/closed; start#72 |
| Patch increment |029 in project/lock/badge/changelog; future-refusal030 |
| Published migrations |001..037 immutable; new038 only |
| Independent review |Complete runtime/SQL/security/upgrade slice; C/H/M0 |
| Test cost |Focused affected checks, one full run before PR |
| Production privacy |Capture off, no keys/subscriptions/destination created on rollout |

## Technical context and ownership

One implementation writer owns runtime,038, tests and release labels. Root owns
this spec/plan/tasks/UML, PB07201, verification prose, canonical issue and run
state. Shared interfaces are serial, never competing writers.

- `agentic_rag/webhooks.py`: owner/scoped gateway, private status and audit.
- `agentic_rag/webhook_delivery.py`: claim/recheck/sign/pinned transport/complete.
- `agentic_rag/webhook_cli.py`, `cli.py`, `mcp_server.py`, `service/engine.py`:
  local/remote contracts, sanitized errors and correct read/write registration.
- `config.py`: only operator-owned key-file and destination policy settings;
  no new dependency, secret-valued environment dump or unsafe arbitrary proxy.
- `sql/038_webhooks.sql`, `service/schema.py`, `service/upgrade.py`: additive
  protected metadata, fail-closed object checks and restore inventories.
- `tests/test_webhooks.py`, `tests/service/test_webhooks.py`,
  `tests/service/test_webhook_upgrade.py`: real PG/RLS/HTTP/receiver/restore.

## Data and capture design

Owner-protected control/subscription/outbox/delivery metadata defaults to capture
off. The operator explicitly changes its persisted switch; APIs cannot enable
the global feature. The same switch gates capture and sender attempts, avoiding
a second unsynchronized configuration flag. A separate worker command is used;
do not start it inside the API or the mining worker.

Triggers cover document insertion/relevant update, claim review, source state,
canonical `lifecycle_events` INSERT (applied/recorded/corrected, joined to the
decision operation), legacy supersedes/duplicate edges and terminal service
ingestion receipts. Edge notices are separately named rather than presented as
canonical lifecycle decisions. Each trigger
only uses whitelisted IDs/states/scopes and never parses audit prose. Emit
source changes separately per visible dependent scope, without cross-scope
lists. An owned job event uses receipt namespace/project and a null domain if
one is not assigned: only a job subscription (null domain, owned namespace and
exact project, job kinds only) can match it. Applied/error/cancelled produce
terminal notices; blocked is recoverable. Omit unrelated maintenance queues.
Capture transition facts immediately, then finalize numeric resource order at
transaction end under the private admission lock as the stale-event discriminator.
Uncommitted internal staging values are never sent. Evidence hashes are optional opaque
fingerprints, not sortable order or final snapshots of subsequent statements.
Source/claim capture runs after their revision bump or from appended history;
multiple notices in one transaction are allowed and correlated. Document that
allocation order across resources is not commit order. Use a
transaction-local generated correlation UUID when no trusted request origin is
available. Rolled-back events and intents roll back with the original change.

Create delivery intents for enabled matching subscriptions transactionally.
Multiple filters cannot duplicate one event/subscription intent. Default limits:
32 subscriptions per namespace,10,000 retained events/deliveries globally,
32MiB encoded payload metadata,4KiB event body and bounded field lengths.
Serialize hard quota accounting at transaction end, after canonical resource
locks have been acquired. A deferred check updates the private control row so
concurrent REPEATABLE READ snapshots cannot admit unseen excess records; a stale
snapshot fails explicitly with serialization failure. It finalizes event order
and exact wire bytes before commit, with no later canonical row locks. Immediate
capture and management must not wait for quota while a producer can still take
canonical locks. Subscription mutations use NO KEY UPDATE, compatible with the
intent foreign-key KEY SHARE lock. Exhaustion rolls back the write explicitly
instead of dropping an event. No live/nonterminal record is pruned.
Terminal acknowledged/cancelled metadata may be pruned after7days explicitly;
dead letters remain inspectable until explicit replay or cancellation. A local
operator can cancel one named dead, revoked or disabled delivery with an
expected-state guard and atomic audit; active leases and pending/retrying work
are refused. Repeating the same cancellation does not renew retention. The
seven-day retention period starts at cancellation; pruning is irreversible. Bound
rotation generations and replay counts. Capture with no matching subscriptions
creates no uncollectable event. Disabled/revoked deliveries are withheld or
cancelled visibly without indefinite retry-budget consumption.

New tables/functions must not inherit arbitrary non-owner default ACL grants.
Use fixed catalog-qualified paths and narrow trigger definer privileges only
where necessary. Scoped clients cannot read delivery material directly, forge
events, change control state or bypass namespace guards. Add ACL-drift checks
before privileged access; owner-only data remains private after role changes.
Management uses narrow fixed-path SECURITY DEFINER RPCs on the caller's existing
scoped writer connection. The RPC enforces trusted namespace/actor/project,
idempotency and optimistic revision and writes audit in that same transaction.
PUBLIC execute is revoked; only the needed writer/read RPCs are granted.
The read RPC returns sanitized own status, never the private credential reference.
Do not use a detached owner transaction, clear GROUP/EXECUTION/LEASE, or publish
a management mutation separately from its queued durable result.

## Authorization and signing

Subscriptions bind trusted namespace/actor and the actual credential reference,
an exact domain/project, allowed kinds, normalized destination and optimistic
revision. An identical create idempotency key replays; mismatched reuse conflicts.
Re-resolve authority for every mutation and immediately before every network
attempt. Documents must remain visible in the captured scope; job metadata is
only sent for the owning receipt namespace/project. Foreign and missing
subscription/delivery IDs have the same denial. Local-only subscriptions bind
the current OS operator; a remote caller cannot manufacture that identity.

Use a private operator-owned regular root-key file and derive distinct
per-subscription/generation HMAC-SHA256 keys. Only a local operator may export
a derived receiver key to a new0600 file outside Git; REST/MCP never return it.
Store no root or derived secrets in database rows or queued arguments. Rotate
the subscription generation with revision/audit, retaining event identity and
using the current generation on retry; consumers must coordinate key changes
and tolerate an already in-flight old generation. Include root key identity
and subscription generation in the wire key identity. A missing/changed root
does not turn a failed delivery into success. Test uses an explicitly generated
minimal test event and the same authorization/transport/signature path.

## Delivery and destination security

Claim one due delivery with a random lease/fence, commit, then send outside any
knowledge transaction. Charge the attempt durably at claim time so repeated process death cannot
evade the six-attempt budget. Lease recovery produces at-least-once behavior. Recheck
the current subscription/control revision and authority before the socket;
completion only updates the matching lease. No request remains pending forever.
Use at most6 attempts with increasing delays and visible dead-letter state;
operator replay clears retry state but preserves event bytes/ID and rechecks
rights. Never retry a canonical write because a receiver failed.

Default public endpoints require HTTPS, no userinfo/query/fragment, bounded
host/path/port, certificate/hostname verification, no redirect or environment
proxy. Resolve all addresses (bounded result count), validate every address and
pin the chosen address for the actual socket. DNS rebinding cannot redirect a
validated hostname to an unvalidated address. An operator allowlist for private
destinations binds exact normalized origin plus explicit allowed CIDRs; no
client may supply or widen it. Metadata/link-local/multicast/unspecified targets
remain blocked even when listed. Explicit loopback HTTP is permitted only for
isolated receiver tests. DNS must also have a hard deadline (for example an isolated bounded resolver
subprocess), not an unbounded getaddrinfo on the sender thread. Normalize
IPv4-mapped IPv6 before classification. The lease exceeds the hard complete
attempt deadline plus completion margin; recheck its fence before a socket
after any delay. Connect/read/total attempt deadlines and bounded
response reads are enforced; errors expose fixed categories, not response text.

## Compatibility and recovery

Archive real7669284 source and build a multi-user/domain028 database with
vectors, original evidence, pin and queued work. Interrupt038 before commit,
retry, verify unchanged original table hashes/ACLs/owners/sequences, and restore
source and target independently including a non-superuser deployment owner.
Run old028 readers and a write with capture off against038. Test opt-in state,
lease/process death and new-runtime retry on restored target. Rollback first
turns capture off and stops the explicit sender, then restores old code while
retaining038 and pending metadata. Never delete schema markers or automatically
restore over newly written production knowledge.

## Tests and measured examples

Freeze meaningful red tests before behavior changes. Real PostgreSQL for
transaction/ACL/RLS/races/quotas; real loopback receiver under the test-only
allowlist for signatures/retries/death; controlled resolver/socket seams for
malicious endpoints without probing real private services. Include key
permissions/rotation, current revocation and clock/replay-window verification.
Focused baseline checks cover old gateways, requests, fence, config, MCP
inventories and upgrades. Retain failed outputs and source hashes. Full suite
only once near PR; no quality or performance claim follows from callback speed.

Root rehearses2–3 real CLI workflows from PB07201 and reconciles architecture
before the independent complete review. Independent reviewer derives an extra
cross-component success/recovery probe rather than duplicating every unit test.

## Interfaces and dependencies

IC-001..005 are defined in the specification. Python3.13/PostgreSQL17/pgvector
and existing dependencies suffice. No model, provider key, external webhook
service, production destination, new framework or network subscription needed.

## Playbook obligations

PB07201 is required before delivery: `docs/webhooks.md`, root-owned, operator
opt-in/signing/receiver/replay/capacity/upgrade/rollback. Independent content
review plus real synthetic CLI/receiver and archived028 recovery rehearsal.
No separate development playbook: these operations reuse the existing verified
upgrade/isolated-database tools, with feature-specific limits in PB07201.

## Architecture findings

See `docs/uml/webhooks-72.md` and AF072-001..006 in `docs/uml/findings.md`.
No implementation may cross an unresolved security boundary to meet a deadline.

## Independent-review correction boundary

Complete review at `18e9fd7` confirmed IR072-001: acquiring quota after a
canonical document lock adds a deadlock when a transaction later writes another
document. IR072-002/PB072-IR-001 confirmed that terminal delivery cancellation
was unreachable and could leave finite capture capacity permanently occupied.
The correction above preserves capture-time scope/state and existing old028
producers. It needs fresh deterministic multi-document, real mining/lifecycle,
edge-versus-memory ordering, quota-boundary READ COMMITTED/REPEATABLE READ,
management/FK/prune, rollback and archived-upgrade tests before acceptance.
Explicit early constraint execution and mixed custom SQL are separately
characterized; no unrestricted lock-freedom guarantee is implied. The local
cancellation procedure must be rehearsed through CLI, including retention and
resumed capture. No full suite is repeated until these corrections are accepted.
