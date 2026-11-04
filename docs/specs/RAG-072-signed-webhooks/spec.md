# Feature Specification: Reliable scoped webhooks

## Stable work ID

- RAG-072; roadmap6.14; [Issue72](https://github.com/phense/agentic-rag/issues/72).
- Approved execution scope under the maintainer's autonomous continuation.
- Baseline: delivered0.6.28/schema037, merge7669284. Target0.6.29/schema038.

## User scenarios

### US-001: React to a committed change (P1)

An authorized writer subscribes an explicitly chosen receiver to one domain and
project. A committed memory/review/source/lifecycle change or an owned ingestion
job transition eventually produces a signed minimal event. A rolled-back change
produces nothing, and delivery never runs inside the knowledge transaction.

### US-002: Recover an unavailable receiver (P1)

An operator can see bounded attempts and dead letters, recover a crashed sender,
and explicitly replay a delivery. The receiver deduplicates stable event IDs and
handles older resource versions without assuming global order or exactly once.

### US-003: Remove external access (P1)

Disabling a subscription, revoking its originating credential/scope or stopping
the feature prevents new sends. Signing material is provisioned and exported by
the local operator in private files; clients never retrieve it through ordinary
tool responses. The operator can rotate a subscription key independently.

## Acceptance criteria

- AC-001: The version1 catalog covers memory creation/change/archive, claim
  review, source withdrawal/reactivation, merge/supersession, and completed or
  failed owned ingestion work. Payloads contain an event UUID, event/resource
  version, timestamp, explicit scope and correlation ID, never bodies, titles,
  quotes, prompts, comments, transcript paths, credential material or raw errors.
- AC-002: Event and intended deliveries commit atomically with the underlying
  write, including old0.6.28 writers. Rollback, process death before commit,
  death after commit and lease recovery cannot lose an acknowledged event.
- AC-003: Existing write authority is required to create/update/disable/test or
  replay an own subscription. The subscription scope is exact and bounded,
  foreign IDs are indistinguishable from missing IDs, read-only credentials
  cannot mutate, and fresh authority is checked immediately before a send.
- AC-004: A receiver can validate a timestamped HMAC-SHA256 signature using a
  distinct key identity and the exact wire bytes. Rotation, duplicate delivery,
  out-of-order updates and replay-window verification have executable examples.
- AC-005: Retries, backoff, timeouts, claim leases, response reads, storage,
  subscriptions and retention have finite limits. Permanent failure is visible
  and does not indefinitely block a transaction or request. Capacity exhaustion
  fails explicitly and atomically rather than silently dropping events.
- AC-006: Each delivery resolves and validates the endpoint again, pins the
  validated IP for the actual connection and verifies TLS against the hostname.
  Redirects and proxy environment variables are ignored. Private/Tailscale or
  loopback receivers require an exact operator-owned origin/address allowlist;
  metadata, link-local, multicast and unspecified addresses remain forbidden.
- AC-007: Demonstrate commit-to-receiver, rollback/crash/retry, outage/dead-letter
  replay, key rotation, revoked authority, malicious DNS/redirects and quota
  rollback through real local components. No external receiver or subscription
  is created on production as part of this feature's rollout.
- AC-008: Populated archived0.6.28 upgrade, interruption/retry and independent
  source/target restores preserve original rows, scopes, vectors, pins, jobs,
  ACLs, owners and sequences. Existing clients work with capture disabled;
  disabling/rolling back code retains the outbox and clearly limits downgrade.

## Functional requirements

- FR-001: Capture is a persisted operator-controlled switch, initially false;
  no startup or migration enables it. Sender execution is explicit and separate
  from API/hooks/mining, not an implicit new daemon on production. Disabling
  capture also prevents new sends while retaining pending metadata.
- FR-002: An exact subscription domain/project and event-kind filter cannot
  expand the originating principal's authority. Delivery re-resolves the saved
  credential reference; permission or resource-scope changes withhold the event.
  Job receipts without an assigned domain are restricted to their owner
  namespace/project; unrelated global maintenance jobs are not broadcast.
- FR-003: Signing secrets never enter outbox rows, request spools, audit text,
  log/error output or ordinary REST/MCP responses. Local operator-only commands
  use owner-only regular files and do not overwrite existing key exports.
- FR-004: At-least-once delivery allows duplicates after an uncertain response
  or process death. A successful2xx is an acknowledgement, not proof of the
  consumer's downstream effect. Non2xx is retried within the bounded schedule.
- FR-005: Resource versions allow rejecting older events; event allocation is
  not a global commit-order promise. Replaying preserves event identity/content
  and uses the current signing generation and current access check.
- FR-007: Subscription scope is discriminated: knowledge requires an exact
  non-null domain/project; job subscriptions require null domain, exact owner
  namespace/project and only job kinds. Applied/error/cancelled receipts are
  terminal notices; blocked is recoverable and emits no failure. The domainless
  job branch requires current project write access and nonempty write domains.
- FR-008: Numeric resource order is separate from an optional opaque evidence
  fingerprint. It advances under resource serialization, including body/title
  changes. A trigger-time fingerprint is never claimed as the final snapshot of
  later statements in the same transaction; multiple notices may share one
  transaction correlation. Consumers compare numeric order for the same resource.
- FR-006: Status, test and replay use the normal authorized CLI/REST/MCP
  gateway. Test is an explicit network operation, never a side effect of create.
  Read tools expose only own scoped, content-free status and no endpoint secret.

## Compatibility boundaries

- Preserve all published001..037 SQL bytes, canonical gateway behavior,
  knowledge/truth/ranking, authentication and existing request/rate budgets.
- Migration038 is additive. Capture defaults off and old writers then incur no
  fan-out, no network or model work. No recoding or provider calls are needed.
- Code rollback first disables capture/sending, then retains038 metadata. Old
  operators may refuse the newer schema; never delete its migration marker.
- Original images and prior feedback/export data remain private and unchanged.
- Runtime supports existing Linux/macOS installations. Host receiver testing
  uses local synthetic data and an explicit test-only loopback allowlist.

## Interface contracts

| ID | Boundary | Contract |
|---|---|---|
| IC-001 | Canonical write to outbox | Atomic minimal event and bounded delivery intent; no network |
| IC-002 | Client to subscription gateway | Trusted actor/reference, exact scope, idempotency, optimistic revision |
| IC-003 | Sender to receiver | Signed exact bytes, stable event ID, timestamp, key identity; bounded attempt |
| IC-004 | Operator to sender | Private signing root, destination allowlist, capture switch and explicit worker |
| IC-005 | Upgrade/recovery | Archived028 source,038 retry/restore, old-reader compatibility and retained outbox |

## Edge cases and assumptions

- A permission change can stop a future send but cannot recall an HTTP request
  already transmitted. Document this finite in-flight boundary explicitly.
- Multi-scope source changes emit scoped notices without revealing other
  dependent IDs. Moving a document cannot expose its destination to a reader
  that lost visibility. No raw queue payload or audit summary is copied.
- All nonterminal records survive retention. Operator cancellation or pruning
  is explicit/audited; capacity denial is recoverable without lost knowledge.
- No guaranteed receiver availability, global ordering, automatic subscription,
  exactly-once downstream effect or improvement to retrieval latency is claimed.

## Success measures

- SC-001: Zero events after rollback; one stable logical event survives a
  commit/send crash and produces duplicate-safe delivery on recovery.
- SC-002: Zero payload/private-content or foreign-ID leaks in the scoped matrix;
  revoked delivery and prohibited destination probes make zero network sends.
- SC-003: Report2–3 measured synthetic workflows with source revision, sample
  counts, commands and error denominators. Focused tests during development;
  one full run before PR on final runtime inputs.

## Playbook obligations

PB07201, `docs/webhooks.md`, is a system deliverable for operators and receiver
authors: opt-in/key provisioning, scoped subscription, local receiver, signature
validation/dedup, outage/replay, revocation, capacity, upgrade and rollback. It
requires independent review and a real isolated CLI/receiver/recovery rehearsal.
