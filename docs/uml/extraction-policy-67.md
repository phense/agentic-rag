# Extraction-policy ownership and replay

Mode: design-time. RAG-067 /6.9. Verified2026-11-01 against baseline `01bc13bd`.
[Specification](../specs/6-9-extraction-instructions/spec.md),
[plan](../specs/6-9-extraction-instructions/plan.md).

## Question: when does an operator preference become durable work?

The operator's file controls only new admission. Uploaded prose and provider output
never supply policy. Current principal authorization stays separate from the
captured preference bundle. This ordering is required because the existing mining
batch row is written only after a provider call succeeds.

```mermaid
sequenceDiagram
    %% Purpose: immutable policy across admission, provider failure and apply retry
    %% Source evidence: jobs.enqueue_mine, service.ingest.accept, mining.mine_session, service.worker.process_source
    %% Requirement IDs: AC-004,AC-005,AC-006,AC-007,IC-002,IC-003
    %% Notation: Mermaid sequenceDiagram
    %% Verified on: 2026-11-01
    actor Operator
    participant File as Validated local file
    participant Admit as Local job or central admission
    participant Queue as Durable private payload
    participant Miner as Mining worker
    participant Bind as Policy binding and audit
    participant Model as Existing provider
    participant Batch as Accepted mining batch
    participant Gate as Existing audited gateway
    Operator->>File: Atomic valid policy replacement
    Admit->>File: Read once and resolve permitted scopes
    Admit->>Queue: Commit source/job with bounded snapshot
    Note over Admit,Queue: Missing legacy metadata means builtin policy
    Miner->>Queue: Claim under current authority
    Miner->>Batch: Read existing accepted output first
    alt Already accepted
        Batch-->>Miner: Existing extraction wins unchanged
    else New extraction
        Miner->>Bind: Bind cursor and snapshot plus audit atomically
        Bind-->>Miner: Committed winner
        Miner->>Model: Bounded preferences and unchanged mandatory rules
        alt Provider fails
            Model-->>Miner: Failure
            Note over Queue,Bind: Retry uses same committed policy
        else Provider succeeds
            Model-->>Miner: Existing structured output
            Miner->>Miner: Enforce categories and limits; ground exact sources
            Miner->>Batch: Commit normalized accepted extraction
        end
    end
    Miner->>Gate: Recheck current scope and apply atomically
    alt Authority revoked or gateway audit fails
        Gate-->>Miner: No partial knowledge writes
        Note over Batch,Gate: Accepted output retained for authorized retry
    else Valid apply
        Gate-->>Miner: Original evidence retained; cursor acknowledged
    end
```

## Design decisions and analysis

- D1: One shared validator/resolver, file-first, no service write/admin UI added.
  CLI local evaluation is explicit; client mode cannot evaluate under false local
  service settings. Unknown configuration fails, not silent fallback.
- D2: Bundle only permitted scopes at admission; source envelopes remain extra-forbid.
  A digest is an identity/integrity check, never an authorization credential.
- D3: New032 binding table protects direct-call retries before provider output.
  Session RLS, bounded JSON and immutable snapshot identity preserve cross-client
  privacy. Existing trusted direct SQL writer assumptions do not expand.
- D4: Legacy queue/window without metadata uses builtin rules. Already accepted
  output is read before custom file parsing; no migration rewrites its JSON.
- D5: A debounced local job's has_more/rerun_requested continuation retains one
  bundle; only a newly admitted job takes a new file version. Cancellation and
  current authorization remain independent of policy rollback.
- D6: All eight existing output channels need deterministic allowlist/limit checks;
  checking memories alone would leave contradiction and suggestion side effects.
  Domainless outputs use global/project preferences. Guidance is advisory; exact
  evidence checks do not prove whether an experiment really was abandoned.
- D7: No source-fragment truncation for policy limits. An all-disabled bundle
  intentionally accepts empty output without a provider call. Invalid settings
  never advance a source cursor.
- D8: Old miners cannot enforce new preferences. Custom activation is gated on
  restarting/upgrading all direct mining writers. Ordinary old client knowledge
  reads/writes remain separately tested. Preupgrade restore loses subsequent
  writes; prospective file rollback does not rewrite admitted work.

Ownership, interface mismatch, failure/recovery, ordering/races, trust boundaries
and migration consistency were checked against the named baseline functions.
No dependency cycle is introduced: policy helpers must not import workers/CLI;
DB binding is isolated behind mining/admission dependencies. There is no mutable
active-policy registry and no second knowledge store.

## Integration flows to derive after implementation

ACF-067-S: strict file → authenticated central admission → durable source payload →
worker binding → controlled provider → category enforcement/evidence gateway →
scoped read and policy identity. Verify original source quote fidelity and zero
foreign policy disclosure.

ACF-067-R: admit policy A → provider failure or accepted-apply failure → replace
file by B or malformed text → authorized retry under A → exactly one apply, with
no second provider call after acceptance. Include revoked credentials, failed
binding audit and snapshot corruption; prove no cursor advancement or partial
knowledge writes, then restore authority/input and recover.

No Mermaid renderer is installed for this feature gate. Diagram directive,
participants, arrows and alt/end pairing were inspected semantically; rendering
is not claimed. As-built reconciliation is still required.
