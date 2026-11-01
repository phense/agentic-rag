# Extraction-policy ownership and replay

Mode: as-built reconciliation before independent acceptance. RAG-067 /6.9.
Verified2026-11-01 against implemented source `115ea50`, coordinator correction
`57af780` and the current-release backup correction. Baseline `01bc13bd`.
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
is not claimed. The coordinator compared the model to the actual admission, binding, provider,
filter and gateway call sites. Independent integration acceptance remains open.


## As-built reconciliation and difference dispositions

| Boundary | Actual code evidence | Disposition |
|---|---|---|
| File contract and deterministic precedence | extraction_policy.parse_document/resolve/resolve_domainless/build_bundle | Matches D1/D2; per-domain and domainless policies share a normalized digest map |
| Atomic admission | jobs.enqueue_mine payload extraction_policy; service.ingest.accept private _extraction_policy inside the source transaction | Matches D2/D5; no custom file leaves no metadata and means builtin legacy |
| Pre-call binding | mining._policy_bundle/bind_policy and SQL032 extraction_policy_bindings trigger/RLS | Matches D3; one immutable binding+audit precedes the provider, regardless of provider failure |
| Accepted output and apply | mining.mine_session reads mining_batches first, then prepare_extraction, accepted commit, existing atomic apply | Matches D4; legacy JSON untouched, new _policy provenance records digest/rejections |
| Deterministic output selection | extraction_policy.enforce over parsed Extraction, all eight channels, after unchanged grounding | Matches D6; parsed hard caps remain authoritative, guidance has no semantic guarantee |
| Current authorization | service.worker.process_source principal scope, before_apply and existing commit checks | Matches D2; captured domains are intersected, never authority grants |
| Read-only evaluation | extraction_cli.dry_run uses reader READ ONLY and prepare_extraction; client evaluation refused | Matches IC-004; root corrected exact sample whitespace and metadata/error-location confidentiality after four failing regressions |
| Legacy compatibility and activation | test_extraction_policy_upgrade actual archived01bc13bd; PB-067 all-miner restart gate | Matches D8 subject to independent PB review; no live/native/multi-host claim |
| Current-release backup | service.upgrade source list now includes actual0.6.20; PB post-upgrade dump uses0.6.20 | Corrected plan implementation: an0.6.20 dump must not be labelled0.6.19; actual backup regression plus affected PB/schema/upgrade rehearsal passed13tests |

Review M1 rejected the original cross-job reuse behavior. A newly admitted
snapshot must match both the work's canonical project and any existing cursor
binding. An invalid admitted project raises policy_snapshot_invalid before
binding. A different admitted digest or a bound project mismatch raises
extraction_policy_conflict before the provider, acceptance or cursor movement.
The worker retains the job and records the error using its existing finite retry
policy; the immutable binding remains intact. Direct retries reuse the existing
binding without reading today's file, but cannot change its project. Accepted
batches still replay unchanged before policy resolution.

The implementer's PB rehearsal admitted a central window but did not mine it;
central integration success/recovery must therefore be derived and exercised by
the independent gate, rather than inferred from the rehearsal title. The
one-second process gate and the file/sample read bounds are named review risks.

AF-067-001..008 are implementation obligations addressed by S1 paths/tests, not
independent acceptance. ACF-067-S/R are still required. Root has not run the full
suite yet. Diagram semantics and error/retry order remain source-inspected only;
no renderer or production execution is claimed.
