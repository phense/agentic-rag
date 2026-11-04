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
    O->>O: Validate bounds; record event and delivery intent
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

Design findings AF072-001..006 live in `findings.md`; independent design
corrections must be reconciled before task execution. As-built reconciliation
and actual success/recovery results remain open.

## As-built reconciliation, 2026-11-04

Runtime revision `2d42176` implements the boundaries above. The integration and
independent acceptance results are recorded separately; this mapping is a source
inspection, not a production or full-suite verdict.

| Boundary | Actual implementation |
|---|---|
| Atomic opt-in capture | SQL038 `rag_webhook_capture` triggers on documents, review/source history, lifecycle events, legacy edges and terminal service windows; `rag_webhook_emit` writes private event/delivery rows in that same transaction. |
| Scoped management | `webhooks.py` calls narrow `rag_webhook_manage`/`rag_webhook_status` RPCs through the current connection. Mutations acquire the quota advisory lock before the subscription row; status is a plain scoped read. Queued GROUP/execution authority is retained. |
| Operator boundary | `webhook_delivery._operator` refuses remote client, CURRENT, GROUP, EXECUTION and LEASE contexts. Capture, private keys and explicit sender have no remote tool. |
| Current authorization | Subscription credential reference is resolved again; current exact scope and resource anchors are checked before DNS and again immediately before the pinned socket. |
| Signing and destination | Owner-only32-byte operator file derives per-subscription/generation HMAC keys. A bounded resolver validates all results; numeric connection, original TLS hostname, no proxies or redirects. |
| Crash and retry | Thirty-second durable leases, attempts charged before I/O, ten-second network deadline, six attempts and eight explicit replays; stale completion cannot publish success or failure. |
| Consumer boundary | Bundled loopback receiver verifies exact bytes/key identity/freshness and durably records event IDs/resource order; no canonical content or downstream effects are retained. |
| Upgrade/rollback | Additive038, unchanged001..037, archived028 readers/writer, separate source/target restores including a restricted owner; runtime rollback requires capture off and retained038 metadata. |

One remaining review question is whether the shared quota lock can add a cycle
when a multi-document canonical transaction acquires a later document lock while
another writer waits for quota admission. This is unproven; the complete review
must disposition it before acceptance. The already reproduced subscription-lock
inversion has a deterministic red/green regression in the implementation.
