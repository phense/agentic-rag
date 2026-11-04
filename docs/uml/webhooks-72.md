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
