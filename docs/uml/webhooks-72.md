# Reliable scoped webhook transaction and network boundaries

Purpose: explain atomic capture, delivery authorization and crash recovery for
RAG-072 AC-001..008 / IC-001..005. Design-time model, verified2026-11-04 against
`store.py`, `evidence.py`, `lifecycle.py`, SQL022, `service/context.py`,
`service/queued_transaction.py` and `service/auth.py`. Mermaid sequence notation;
semantic source inspection, not a claimed renderer run.

```mermaid
sequenceDiagram
    participant W as Authorized canonical writer
    participant P as PostgreSQL transaction
    participant O as Scoped subscription and outbox
    participant S as Explicit sender
    participant A as Current authentication policy
    participant R as Pinned destination
    W->>P: Audited knowledge, review, lifecycle or receipt change
    P->>O: Trigger checks capture and matching exact scopes
    O->>O: Capture immutable facts and private delivery intent
    P->>O: Deferred admission after canonical mutations
    O->>O: Serialize hard quota; finalize order and exact bytes
    alt Canonical write or quota fails
        P-->>W: Rollback knowledge, audit and outbox
    else Commit succeeds
        P-->>W: Ordinary result; no network wait
        S->>O: Claim due delivery and commit fenced lease
        S->>A: Re-resolve subscription credential and current scope
        alt Disabled, revoked or resource moved out of scope
            S->>O: Record withheld or cancelled status
        else Current authorized subscription
            S->>S: Resolve and validate every address, derive signing key
            S->>R: Signed exact bytes over validated pinned socket
            alt 2xx acknowledgement
                S->>O: Complete only matching current lease
            else Error, timeout or crash
                S->>O: Bounded retry or visible dead letter
            end
        end
    end
```

No receiver call occurs while a knowledge transaction is open. A crash after
the receiver accepted but before completion can cause duplicate sends; stable
event IDs make them deduplicable. Per-resource versions help reject older
notifications; neither global commit ordering nor exactly-once side effects
are promised. Current policy is checked before each socket; an already sent
request cannot be recalled after revocation.

Capture covers lifecycle_events explicitly, including merge/duplicate,
supersession and correction, rather than assuming every decision creates an
edge. Job events are owned ingestion receipts with explicit project and owner
namespace; no global maintenance-job broadcast. A source notice never includes
dependent IDs from another subscription scope. Canonical data, RLS, execution
fences and signing material retain separate ownership.

## Derived integration scenarios

- ACF072-S: Real scoped gateway write commits, separate sender sends a minimal
  signed event to an explicit loopback test receiver, receiver verifies exact
  bytes and deduplicates. Knowledge and audit commit before network activity.
- ACF072-R: Kill after committed intent and after receiver acknowledgement;
  reclaim the lease, observe a duplicate event ID, then revoke the originating
  credential before another attempt. No subsequent network send; original
  knowledge, receipt ownership and retained outbox are intact.
- ACF072-U: Archived028 populated store interrupts038 before commit, retries,
  independently restores both backups and runs old028 readers/writer while
  capture remains off. Preserve rows/ACLs/owners/sequences/vectors/pins/jobs.

Design findings AF072-001..006 live in `findings.md`; their corrections are
implemented and reconciled below. Actual success/recovery results are recorded
in the verification evidence.

## As-built reconciliation, 2026-11-04

Runtime revision `128d2cf` implements the corrected boundaries above. The integration and
independent acceptance results are recorded separately; this mapping is a source
inspection, not a production or full-suite verdict.

| Boundary | Actual implementation |
|---|---|
| Atomic opt-in capture | SQL038 `rag_webhook_capture` triggers on documents, review/source history, lifecycle events, legacy edges and terminal service windows; `rag_webhook_emit` stages capture-time facts and delivery rows in that same transaction. Deferred event/subscription/delivery admission finalizes sortable order and exact wire bytes under a private control-row update at commit. |
| Scoped management | `webhooks.py` calls narrow `rag_webhook_manage`/`rag_webhook_status` RPCs through the current connection. Mutations use NO KEY UPDATE, compatible with delivery FK KEY SHARE. Hard admission is deferred; status is a plain scoped read. Queued GROUP/execution authority is retained. |
| Operator boundary | `webhook_delivery._operator` refuses remote client, CURRENT, GROUP, EXECUTION and LEASE contexts. Capture, private keys, named terminal cancellation and explicit sender have no remote tool. Cancellation is atomic with audit, clears leases and preserves the first cancellation time on repeat. |
| Current authorization | Subscription credential reference is resolved again; current exact scope and resource anchors are checked before DNS and again immediately before the pinned socket. |
| Signing and destination | Owner-only32-byte operator file derives per-subscription/generation HMAC keys. A bounded resolver validates all results; numeric connection, original TLS hostname, no proxies or redirects. |
| Crash and retry | Thirty-second durable leases, attempts charged before I/O, ten-second network deadline, six attempts and eight explicit replays; stale completion cannot publish success or failure. A local operator retires a named dead/revoked/disabled delivery; seven-day pruning skips locked metadata rows. |
| Consumer boundary | Bundled loopback receiver verifies exact bytes/key identity/freshness and durably records event IDs/resource order; no canonical content or downstream effects are retained. |
| Upgrade/rollback | Additive038, unchanged001..037, archived028 readers/writer, separate source/target restores including a restricted owner; runtime rollback requires capture off and retained038 metadata. |

Independent review at `18e9fd7` confirmed IR072-001 (canonical multi-document
quota deadlock) and IR072-002 (missing terminal retirement). The implementation
correction at `128d2cf` preserves immediate scope/state facts, defers strict
admission and resource-order finalization, and adds audited local cancellation.
The finalizer takes no canonical row locks. Its control-row update fences stale
REPEATABLE READ snapshots; delivery admission also preserves hard quotas if a
caller forces constraints early. Arbitrary later custom-SQL resource locking
has no deadlock-freedom guarantee; normal API/CLI/mining producers keep default
INITIALLY DEFERRED behavior.

The corrected157-test selection covers the exact concurrency failure, mixed
edge/memory order, READ COMMITTED/REPEATABLE READ quotas, real mining/lifecycle,
management/FK/prune interaction and archived028 recovery. Root's47-command CLI
rehearsal verifies signed delivery plus explicit capacity retirement/recovery.
Independent correction review accepted the changed architecture and code with
C0/H0/M0/Low0. Its remaining operator-inventory procedure finding was corrected
and rehearsed with a genuinely revoked remote owner, without widening scoped
status. None of these results substitutes for the final full suite or production proof.
