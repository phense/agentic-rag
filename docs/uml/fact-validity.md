# Atomic fact validity — as-built view

Question: where is replacement authority checked, and what survives a crash?
Requirements: RAG-006 AC-001–AC-007, IC-001–IC-004.
Sources: store.py save_document, mining.py mine_session/_apply_extraction,
mining_window.py read_window, sql/010_project_scope.sql, RAG-006 plan.
Notation: Mermaid sequence. Verified 2026-09-05 by semantic source inspection;
rendering not claimed. Ownership and ordering are shown; PostgreSQL is one store.

```mermaid
sequenceDiagram
    participant S as Source window
    participant M as Mining
    participant G as Audited gateway
    participant D as PostgreSQL
    participant R as Reader
    S->>M: Consumed sanitized event fragments and references
    M->>M: Validate whole-fragment declaration, quote, role and time
    M->>D: Commit normalized accepted batch
    M->>D: Lock accepted batch
    M->>G: Save atomic assertion within batch transaction
    G->>D: Lock scope/entity/attribute key
    G->>D: Read bounded candidates and classify
    G->>D: Save immutable assertion, append sources, disposition and links
    alt Failure before application commit
        M->>D: Roll back all effects; accepted batch remains
        M->>M: Retry accepted output without another model call
    else Success
        M->>D: Commit effects and result together
    end
    R->>D: Select scope and valid time before candidate limits
    D-->>R: Eligible current or historical assertions
```

The trust boundary is structured model output to the gateway: model-supplied role,
source text and timestamps are never accepted without matching the consumed source.
Explicit CLI/MCP evidence is an operator assertion, not independently verified external
truth. No automatic migration assigns validity to old documents. Pins are independent.

As-built reconciliation: source fragments are capped at 64 without cursor loss;
automatic authority uses conservative whole-fragment declarations. Distinct duplicate
attestations append idempotently. Curation revalidates the evidence epoch under locks
after a model response. Unselected manual graph browsing retains history. These are
explicit authority/compatibility clarifications, not omitted requirements.
