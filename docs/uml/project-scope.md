# Project scope selection (design and implementation contract)

Question: where must scope be enforced to prevent candidate-limit and graph bypass?
Requirements: RAG-005 AC-001..006. Evidence: search.py/003_search.sql,
004_graph.sql, store.py, mining.py, curation.py, hooks/*.py. Owner: coordinator.
Verification: 2026-09-05; Mermaid source inspected semantically, not rendered.

```mermaid
flowchart TD
    Input[CLI / MCP project / hook cwd] --> Resolver[Canonical project and pin anchor resolver]
    Resolver --> Select[Scope selection]
    Select --> Candidates[Vector and FTS candidates before limits]
    Select --> Recall[Signal recall and startup assembly]
    Select --> Graph[Every recursive graph hop]
    Resolver --> Gateway[Audited write gateway]
    Gateway --> Scope[Stored project scope]
    Scope --> Candidates
    Scope --> Recall
    Scope --> Graph
    Scope --> Curation[Equal known scope only]
    Legacy[Legacy provenance and pin scopes] --> Repair[Audited idempotent backfill]
    Repair --> Scope
    Repair --> Unknown[Unknown inventory for review]
```

No auth boundary is added. Explicit get/path without selection stays a deliberate
cross-project browse. Profiles must consume Select when later implemented.
