# Entity aliases: reversible evidence selection

Question: What changes when an alias is confirmed or revoked, and which evidence
can a reader traverse? Mode: design-time; verified2026-10-04 by semantic source
review (no renderer dependency). Requirements: RAG-5.8 AC-001–007.
Evidence: spec/plan, store.py, validity.py, evidence.py, db.py, schema001–017.

```mermaid
sequenceDiagram
    participant O as Authorized operator
    participant G as Audited store gateway
    participant D as Shared PostgreSQL
    participant R as Scoped reader
    O->>G: Alias and anchor names plus original source attestation
    G->>D: Lock exact scope and domain
    G->>D: Save immutable evidence claim and review relation
    O->>G: Confirm after checking names and support
    G->>D: Recheck support, competing anchors and chains
    G->>D: Accept relation and audit in one transaction
    R->>D: One snapshot: exact scope, domain, support and current facts
    D-->>R: Anchor and direct aliases with original chunk citations
    O->>G: Revoke with reason
    G->>D: Revoke relation and append audit, retain all facts
    R->>D: Repeat selection
    D-->>R: Separate identities, original history intact
```

Supported upgrade: transactionally add018, repeat bounded gateway backfill, activate
approved code, reconnect selected clients. Old assertions remain exact-name visible
without attachments. DDL interruption rolls back; backfill interruption rolls back
only its unfinished batch. Code rollback leaves018. Full restore is a separate
operation whose data-loss limit is the backup snapshot.
