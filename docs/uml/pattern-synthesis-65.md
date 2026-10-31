# Scoped synthesis acceptance and publication

- Work: RAG-065 /6.7 / Issue65; mode: as-built, reconciled against `a44c0a1` (runtime `8f0911a`).
- Question: where must authority, evidence and policy be checked so a retried background inference never becomes stale or unauthorized truth?
- Requirements: AC-001..009; IC-001..004; plan `../specs/6-7-pattern-synthesis/plan.md`.
- Evidence: `synthesis.py` (`_plan`, `_held`, `_gate`, `_process_locked`, `_finish`, `recover`), `store.save_claim`, `service.context.ServiceConnection`, worker/central runner and migration030 (six synthesis tables and queue RLS). Integration fixtures: `tests/test_synthesis_forward.py`, `tests/test_synthesis_apply.py`, `tests/service/test_synthesis_transports.py`, `tests/service/test_synthesis_upgrade.py` and `tests/service/test_synthesis_playbook.py`.
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
    Note over C,D: Before first pattern: inventory, upgrade and restart all direct readers at 0.6.18
    C->>G: Enable scoped forward epoch or explicit bounded backfill
    G->>D: Audited policy and durable work
    W->>D: Plan unprocessed originals and bounded recent context, fit complete input budget
    Note over W,D: Membership decides consumption; rotating scan position cannot skip late commits
    W->>D: Persist finite snapshot and claim existing queue job
    W->>D: Revalidate current credentials, policy and source snapshot
    alt No accepted output
        W->>P: Sanitized original spans, finite schema and budgets
        P-->>W: Cited hypothesis parts or non-conclusion (semantic truth not proven)
        W->>D: Recheck policy, source versions and scope
        W->>D: Persist structurally validated accepted output once
    else Accepted output retained after interruption
        D-->>W: Reuse exact accepted output without another model call
    end
    W->>D: Revalidate and lock current policy/source versions
    alt Current authority, policy and originals
        W->>G: Apply inference with stable application identity
        G->>D: Atomically save inference, dependencies, audit and new-original processed membership
    else Disabled, revoked, changed, expired or conflicting
        W->>D: Withheld, no application or consumption on changed gate
    end
    Note over W,D: Current non-conclusions also atomically mark new originals analysed; never context-only runs
    opt Accepted run parked after finite apply retries
        C->>G: Explicit recover as authorized writer (local or central)
        G->>D: Audit and requeue accepted run through scoped queue RLS
        W->>D: Recheck gate and reuse accepted output without provider
    end
    C->>G: Inspect pattern or retrieve confirmed inference
    G->>D: Recheck current scope, all dependencies and policy
    D-->>C: Current suggestion and exact authorized source links, or withheld
```

No edge connects generated patterns back to the candidate pool. Provider output has no authority to choose a scope, introduce a source, mark a user statement or confirm evidence. The gateway owns application; the existing worker owns execution and durable retry. Policy disable and source drift fail closed at reads as well as writes. Keeping a rejected/disabled suggestion for audit does not authorize exposing its stale body.

Differences from design: processed membership replaces the unsafe time cursor; snapshots distinguish new originals from bounded recent context, so adjacent runs can share corroboration. Input fit precedes scheduling; oversized or below-floor support stays visibly pending. A budget-blocked backfill creates no run and retains its cursor and batch allowance, exposing `waiting: input_budget_below_floor` through status and CLI. Application identity binds semantic generation parameters, excluding the enable/disable counter. Every post-provider terminal outcome rechecks the gate. Exact citations verify provenance, not semantics: the frozen C2 false suggestion remains disclosed and excluded from ordinary retrieval while unreviewed.

Compatibility correction: old0.6.17 code lacks direct get/evidence/history/graph withholding. Mixed direct readers are forbidden after first generation; code-only rollback after any pattern exists is unsupported. PB-065-OPS B0 inventories and restarts all known direct clients before enablement. Unlisted/offline hosts cannot be discovered automatically. Recovery is new-code repair/disable or an authorized verified pre-upgrade restore with explicit post-backup-write reconciliation.

Source reconciliation is complete; the independent success/recovery and playbook gates must be rerun for this changed architecture. The original success/recovery probes at `0e37a82` exposed the central queue defect and cannot certify the corrected source. Full final verification remains pending. No renderer was invoked; Mermaid source received semantic review only.
