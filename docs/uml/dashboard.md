# Dashboard trust and recovery model

Work RAG-059, as-built reconciliation complete, source 2026-10-30: service/api.py, auth.py, engine.py, requests.py and implemented schema025. Question: how can a browser administer a file-owned policy without granting knowledge access or losing audit on process failure? Requirements FR-001..009, contracts IC-059-01..05. Mermaid sequence notation; directive, participants, alt/end pairing, message order and labels were semantically validated on 2026-10-30. No diagram render is claimed.

```mermaid
sequenceDiagram
    actor Operator
    participant Browser
    participant UI as Dashboard boundary
    participant Policy as Owner-only policy file
    participant DB as PostgreSQL
    participant Engine as Scoped engine/queue
    Browser->>UI: Cookie session + origin + CSRF
    UI->>DB: Validate exact live session
    UI->>Policy: Reload current permissions
    alt Knowledge request
        UI->>Engine: Current scoped principal
        Engine->>DB: RLS + bounded original-backed query
        DB-->>Browser: Scoped result
    else Explicit administrative apply
        UI->>Policy: Acquire owner-only file lock (flock)
        UI->>Policy: Check expected revision and validate change
        UI->>DB: Commit nonsecret prepared audit (old/new digest)
        UI->>DB: Lock exact session row; revalidate authority/clock expiry
        UI->>Policy: Atomic owner-only replace + fsync
        UI->>DB: Mark applied + commit; release session lock
        UI-->>Browser: Safe IDs, generated credential once
    end
    Note over UI,DB: Restart: reconcile prepared old/new digest before next mutation; unknown drift fails closed.
    Operator->>Policy: External file edit
    Note over UI,Policy: File is sole authority. Stale browser preview returns409.
```

No browser DDL/move occurs. Setup state is saved independently of runtime configuration; validation reports safe codes. Compatibility uses the existing bounded authenticated HTTP transport without opening a spool, against an operator-owned URL/token. Its saved fingerprint includes URL and credential revision; no reachable/authenticated protocol response means no green check. Custom default ACLs are stripped only from the three new control tables; unexpected later grants or owner memberships fail schema validation. Existing-data discovery blocks fresh reinitialization. Observed versions/last-seen are metadata only. Admin inventory can list principals but scoped counts and memories never bypass current RLS.

Independent whole-feature review derived and verified the bootstrap→enroll→scoped-browser success and prepared-audit process-crash→restart→replay/revocation recovery scenarios. Durable tests live in `tests/service/test_dashboard_integration.py`; all three pass, including unknown-digest refusal. Round3 reran them within152 repository tests plus six independent inherited-authority probes, all passing. See the [verification record](../verification/issue59-dashboard.md) for revisions and evidence limits.
