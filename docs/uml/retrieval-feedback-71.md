# Retrieval feedback ownership (RAG-071)

- Mode: design-time,2026-11-03, source9ee02b7, Python/service/SQL001..036 inspected.
- Purpose: AC-001..009 and IC-001..005; questions below answer authority, privacy
  and atomicity before implementation. Mermaid source semantic review; no renderer
  dependency added.

## Q1: Can feedback reuse retrieval without acquiring truth authority?

```mermaid
flowchart LR
  C[Writer: CLI or authenticated REST/MCP] --> F[Explicit feedback search gateway]
  F --> S[Existing scoped search]
  S --> K[(Canonical knowledge: unchanged)]
  F --> E[(Immutable metadata event)]
  C --> M[Versioned signal gateway]
  E --> M
  M --> R[(Feedback signal and bounded history)]
  M --> A[(Existing audit log)]
  M --> U[(Namespace-only accounting counters)]
  O[Local operator] --> P[Approve current expected source and safe query]
  R --> P
  K --> P
  P --> V[(Private approvals: owner only)]
  V --> X[Sealed private export]
  X --> B[Read-only confirmed-failure evaluator]
```

There is no edge from feedback back to source trust, claim review or ranking.
Ordinary search does not capture an event. New writer tools preserve the read-only
server contract. Metadata snapshots contain IDs/versions/digests, never bodies or
raw queries. Local operator approval is the only path retaining a reconstructed
query, screened and kept in an owner-only table/private export.

## Q2: What makes retries, revocation and updates safe?

```mermaid
sequenceDiagram
  participant C as Authenticated client
  participant G as Scoped feedback gateway
  participant D as PostgreSQL
  C->>G: event/key or signal/expected revision
  G->>D: namespace lock; visibility, rate and quota checks
  alt matching idempotent replay
    D-->>C: existing event/signal
  else new or current revision
    G->>D: scoped read-only repeatable-read search and versions
    Note over G,D: Separate reader; writer retains audit/receipt commit
    G->>D: event or signal/history plus audit
    G->>D: commit with current credential authority
    D-->>C: record/revision
  else stale, foreign, revoked, full or audit failure
    G->>D: rollback
    G-->>C: uniform unavailable, conflict or bounded refusal
  end
```

Accounting metadata remains namespace-visible when a domain/project grant is
revoked. Retained counts and conservative byte charges therefore cannot reset
when a client cycles scopes; counters, signal/event and audit commit atomically.
No source IDs or content are exposed by this accounting table.

Signal RLS requires immutable namespace plus existing domain/project rules.
Feedback `fb1:` versions bind canonical `ev1:` plus a title/body digest, so plain
legacy memory edits also invalidate a captured reference. Canonical evidence
versions and their consumers remain unchanged. No raw text is retained.

Idempotency keys are actor/client-scoped. Aggregation uses stable user identity,
so a second machine is not a second independent actor. Approvals bind signal
revision and expected-source versions; update/retract/source withdrawal makes
them stale without changing knowledge. Never use a cached permission decision.

## Q3: What survives upgrade and rollback?

Migration037 adds event/signal/approval and namespace-accounting tables only. Existing knowledge, vectors,
jobs and policies are unchanged. Upgrade invokes no model or capture. Old027
readers continue against036-compatible knowledge; old schema-aware operators may
refuse the newer migration list. Disabling feedback and returning to027 code
retains all feedback rows. Independent dump/restore covers both original and new
tables, and an interrupted migration rolls back fully.

## Derived integration probes

- Success: scoped search -> event -> negative feedback -> explicit safe query and
  current expected-source approval -> private export -> read-only miss/hit report.
  Whole connected source families remain in one split; knowledge hashes equal.
- Recovery: force an audit error, observe no signal/history, retry same key once;
  revoke the writer or change source version before approval/export, observe
  refusal/withheld without leaked metadata, restore authority and retry explicitly.
- Upgrade/recovery: populated archived027 -> interrupted037 -> unchanged source ->
  retry -> feedback writes -> independent source/target restores -> old027 read.

## Findings to implementation

AF071-001..006 in `findings.md` are binding response items. As-built reconciliation
must check tool registration, permission rechecks, private-query ownership,
idempotency/audit transactions, family independence and actual upgrade evidence.

## As-built reconciliation (2026-11-03)

Runtime4cc570f/3ad0f2a implements the topology above. `feedback.py` owns explicit
commit/rollback, namespace locks, conservative namespace accounting and current
`fb1:`/eligibility checks. `feedback_cli.py`, MCP registration and the existing
service tool dispatcher share that gateway. `benchmark/feedback.py` owns the
local approval boundary and private read-only evaluation, dispatched before the
unchanged confirmed-correction format validator. Schema037 adds four tables and
no new definer or leakproof function.

Derived success/recovery probes are executable in
`tests/service/test_retrieval_feedback.py`, `tests/test_retrieval_feedback.py`,
`tests/benchmark/test_feedback.py` and `tests/service/test_feedback_upgrade.py`.
The74+33 targeted checks and14-command CLI rehearsal prove scoped capture,
mutation, audit/revocation rollback, private miss reproduction and populated
source/target restore. The whole source-family split is tested with copied spans;
six approved negative cases cover both dev/test. No evaluation profile is tuned.
AF071-001–006 are implemented with this evidence; independent acceptance and
final full verification remain pending. See the linked verification record.

### First independent-review correction

Correction9d31fe9 preserves the writer transaction and opens one separately
scoped, read-only repeatable-read connection for retrieval and every retained
document/source version. Queued grouping is bypassed only for reader creation;
current principal, lease, execution pins and final writer authority checks remain.
A concurrent audited text update now leaves the returned original content bound
to its original version; a later read marks it stale. This is limited to explicit
feedback capture and does not change ordinary search isolation.

Migration037 strips every nonowner default grant from its four new tables before
assigning the intended privileges. Local private operations share the existing
service owner-only ACL validation, including column rights and owner membership,
and refuse a later exposure. Historical table ACLs and migrations001–036 remain
unchanged. Actual queued capture/replay preserves one audit and durable origins;
revocation at the audited boundary rolls back event, audit and usage while the
accepted queue receipt becomes failed without a result.

The fresh14-command CLI rehearsal on9d31fe9 passes in31.405s with all50 original
public tables unchanged. Independent correction acceptance and full verification
are still pending. The earlier S1/S2 figures above remain historical evidence.
