# RAG-009 context lifecycle

Question: how does a rebuildable view remain safe after source correction and failed
refresh, without giving reader hooks write authority? Design-time;2026-09-06.
Evidence: specs/RAG-009-project-context/plan.md; hooks/session_start.py; jobs.py;
worker.py; evidence.py; scope.py. Owner: coordinator. Scope: cache/host boundaries.

```mermaid
sequenceDiagram
    participant H as Hook or CLI or MCP reader
    participant V as Context and profile reader
    participant D as Canonical PostgreSQL
    participant Q as Existing queue and writer
    H->>V: project, mode, real turn
    V->>D: scoped revision and current eligibility
    D-->>V: cached IDs plus live source records
    V-->>H: bounded advisory text or dated fallback
    alt Startup
        H->>Q: schedule missing or stale profile before emit
        H->>H: emit startup context without receipt
        Q->>D: audited atomic reference refresh
    else Prompt with real turn
        H->>H: check receipt, emit, then record receipt
    end
    Note over Q,D: Failure rolls back cache; next read revalidates old IDs
```

AF-009A: cache freshness cannot rely on max audit ID (out-of-order commits) or a prompt
hash. Use visible tuple revision + revalidation, and real turn identity for receipts.
AF-009B: candidate-level dedup can erase evidence from emitted output. Budget before
recording dedup/receipt; preserve entire pins and prioritize checkpoint restoration.
AF-009C: async failure must not erase usable context or upgrade legacy evidence.
Atomic gateway update, dated filtered view/fallback, reader-only contract.

Syntax reviewed against the sequence participant/message grammar; no renderer dependency.
As-built reconciliation2026-09-06: profiles.revision returns one server-aggregated
metadata digest; _rows resolves<=12 documents with<=8 evidence spans each. Refresh
uses store.refresh_profile, jobs.enqueue_profile and worker.process_job. context.build
wraps existing startup pin/checkpoint fitting; prompt_recall calls the same reader and
records context_gate receipt only after emit. Missing turn IDs disable receipts.
Source refresh failure uses transaction rollback; profile read revalidates current IDs.
CLI context and memory_context use reader connections; profile --refresh is writer-only.
All sequence messages map to these implemented functions. No model or scheduler added.
Independent architect derived the startup queue->worker->reader->prompt delivery test
and a failed worker refresh after cache write with withdrawn source/replacement. Implemented
in tests/test_project_context.py::test_architecture_startup_queue_worker_reader_and_turn_delivery
and ::test_architecture_failed_worker_refresh_keeps_dated_revalidated_view. Both pass in the 757-test full suite (29.14s). Rendering-failure scheduling also has a passing regression.
