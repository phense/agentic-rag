# As-built model: RAG-5.9 incremental ingestion

Source1294d6c, schema018; candidate019. The cache is disposable derived state,
not an evidence or access-control boundary. Original document/chunk/evidence writes
retain their gateway and database grants. Pure inference can run in two threads;
all SQL decisions and writes stay with the caller's single connection.

```mermaid
sequenceDiagram
    participant M as Accepted mining batch
    participant P as Bounded preparation
    participant H as Local embedding HTTP
    participant G as Audited save gateway
    participant D as PostgreSQL
    M->>D: Durable accepted extraction; lock application row
    M->>P: Final sanitized title/body inputs (bounded group)
    P->>D: Optional savepoint-isolated cache reads
    P->>H: Missing exact inputs, at most two requests
    H-->>P: Validated ordered vectors; recheck digest
    P-->>M: Context-local prepared map, no cache writes
    loop Original item order
        M->>D: Existing dedup decision against current SQL state
        M->>G: Immutable claim/assertion gateway, commit=False
        G->>D: Canonical document and complete chunk stream
        G->>D: Optional cache function, global try-xact lock
        G->>D: Atomic derived fill/eviction and audit
    end
    M->>D: Application result and audit commit
    Note over M,D: Crash before commit discards application/cache; accepted extraction remains
    Note over M,D: Crash after commit reuses result; queue acknowledgement remains separate
```

II-S01/02 bind raw/context input and model versions; II-R01/S03 cover optional SQL
failures and nonblocking concurrent writers; II-S04 retains stale-source guards and
unchanged queue ordering; II-S05 covers complete oversized pages. II-R02 executes
actual process death before/after application commit. II-R03 executes source018
compatibility, simultaneous old/new transactions,019 DDL rollback/retry, strict
source/target/private-copy restore and guarded Git activation/recovery.

Independent architecture and complete diff reviewers checked the final application
boundary. Their operational findings added actual server/database backup identity,
backup freshness, repeated pre-switch checkout guards, owned child gates, frozen
model identity and literal content/vector oracles. Final evidence/ready status is
recorded in [verification](../verification/incremental-ingestion.md).
