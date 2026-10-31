# Scoped synthesis acceptance and publication

- Work: RAG-065 /6.7 / Issue65; mode: design-time.
- Question: where must authority, evidence and policy be checked so a retried background inference never becomes stale or unauthorized truth?
- Requirements: AC-001..009; IC-001..004; plan `../specs/6-7-pattern-synthesis/plan.md`.
- Evidence: existing `evidence_contract`, `store.save_claim`, `service.context.ServiceConnection`, `service.worker`, `worker`, `jobs` and migration029. Proposed new nodes are explicitly prospective.
- Owner: coordinator; verification2026-10-31: semantic Mermaid-source review, no renderer claim.

```mermaid
sequenceDiagram
    participant C as Authorized client
    participant G as Shared gateway
    participant W as Existing singleton worker
    participant P as Structured provider
    participant D as Canonical scoped store
    C->>G: Preview explicit domain/project
    G->>D: Read eligible original spans and portable versions
    D-->>C: Bounded preview, independence and budgets
    C->>G: Enable scoped forward policy or explicit bounded backfill
    G->>D: Audited policy and durable work
    W->>D: Claim bounded due work under worker authority
    W->>D: Revalidate current credentials, policy and source snapshot
    alt No accepted output
        W->>P: Sanitized original spans, finite schema and budgets
        P-->>W: Supported hypothesis parts or non-conclusion
        W->>D: Persist validated accepted output once
    else Accepted output retained after interruption
        D-->>W: Reuse exact accepted output without another model call
    end
    W->>D: Revalidate and lock current policy/source versions
    alt Current authority, policy and originals
        W->>G: Apply inference with stable application identity
        G->>D: Atomically save derived suggestion, dependencies and audit
    else Disabled, revoked, changed, expired or conflicting
        W->>D: Bounded withheld/non-conclusion state, no canonical application
    end
    C->>G: Inspect pattern or retrieve confirmed inference
    G->>D: Recheck current scope, all dependencies and policy
    D-->>C: Current suggestion and exact authorized source links, or withheld
```

No edge connects generated patterns back to the candidate pool. Provider output has no authority to choose a scope, introduce a source, mark a user statement or confirm evidence. The gateway owns application; the existing worker owns execution and durable retry. Policy disable and source drift fail closed at reads as well as writes. Keeping a rejected/disabled suggestion for audit does not authorize exposing its stale body.

As-built reconciliation and architecture-derived success/recovery tests remain pending S2.
