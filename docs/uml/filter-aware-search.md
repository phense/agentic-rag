# Filter-aware retrieval: transaction ownership

Question: How does a scoped search preserve caller budgets/state and work on015/016?
Source: RAG-5.5 plan; search.py, db.py,013/015 SQL. Requirements AC-001–006/IC-001–004. As-built sequence; source and real transaction/cancellation tests verified2026-10-03; no renderer run.

```mermaid
sequenceDiagram
    participant Client
    participant Search
    participant Planner
    participant SQL
    Client->>Search: Existing scoped search arguments
    alt Exact selector or explicit baseline control
        Search->>SQL: Existing candidate function
    else Planned function absent on015
        Search->>SQL: Existing contextual fusion
    else Default auto on016
        Search->>Planner: Protected function discovery, then vector query
        Planner->>SQL: Nested savepoint, or own idle/autocommit read transaction
        Planner->>SQL: Inspect installed capabilities and caller settings
        Planner->>SQL: Local bounded settings before candidate statement
        SQL->>SQL: Materialize eligible probe once; reuse for exact or gate ANN
        SQL->>SQL: Eligibility and per-document diversity before final pool
        alt Successful statement
            SQL-->>Planner: Original-source candidates
            Planner->>SQL: Restore settings; release savepoint
        else Timeout or external cancellation
            SQL-->>Planner: Query cancellation
            Planner->>SQL: Roll back savepoint only
            Planner-->>Search: Propagate cancellation safely
        end
    end
    Search-->>Client: Existing original spans/citations or safe error
```
