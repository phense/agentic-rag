# Central service: trust boundary and durable acknowledgment

Purpose: identify authority for scope, input durability and worker ownership (FR-001..009). Design evidence: `docs/specs/6-0-central-service/plan.md`, existing `db.py`, `mcp_server.py`, `worker.py`, `mining.py`. Mode: as-built with independently derived integration scenarios implemented; complete-range review pending. Reconciled2026-10-29 by semantic source inspection (no renderer result claimed).

```mermaid
sequenceDiagram
    participant H as Agent hook
    participant L as Durable local spool
    participant A as Authenticated API
    participant D as PostgreSQL
    participant W as Central worker
    H->>L: Persist bounded evidence and handoff
    L-->>H: Local durability
    L->>A: Window and predecessor cursor
    A->>A: Verify credential and current scope
    A->>D: Require migrated RLS and non-bypassing roles before engine access
    A->>D: Atomic window, publication teams, stream head and queued job
    D-->>A: Commit
    A-->>L: Durable receipt
    L->>L: Retire acknowledged upload
    W->>D: Hold cross-host singleton lock
    W->>W: Revalidate owner policy
    W->>D: Accept model batch then audited atomic application
    Note over W,D: Crash replay uses accepted batch; no duplicate application
```

The client has no database/model credentials. Every knowledge connection receives immutable authenticated scope before executing engine code; SQL filtering protects graph joins/counts as well as direct lookup. Legacy local connections keep existing permissions. Security-definer chunk writers require explicit scope checks. User login grants an expiring session; a configured machine key identifies both the machine and its bound user. Neither a caller hostname nor a project argument is authority.

S058-01 review reconciliation: startup and every scoped connection fail closed on
missing migration/RLS/old-row guards or privileged roles. Remote checkpoint lookup
and rendering use logical project identity; operator diagnostics are status-only.
The original row and its proposed replacement both require write authority.

S058-02 reconciliation: a worker's keeper holds the exclusive owner lock. Each
actual data connection also holds a shared execution pin; a replacement must
briefly obtain the exclusive execution pin before orphan recovery. This protects
in-flight inference when only one of the old process's connections dies. Queries,
application and commits check keeper authority; an old runner exits1 after loss.
Cancellation shares the source window lock, checks the applied batch, and terminal
states survive error cleanup. Source admission atomically commits input, cursor,
queue and audit before ACK. A trusted fixed-aggregate storage check gates fresh
writes; scoped canonical connections retain principal authority. Exact receipt
replay, reads and cancellation remain available under storage/backlog pressure.


S058-03 reconciliation: operator commands run outside service request scope.
Inventory streams stable ordered row hashes and records original grants,
sequences, ownership and migration history. A strict snapshot restore into an
owned temporary database precedes local DDL. Original preservation and additive
DDL share one commit. A database read-only default fences returning legacy
writers; role overrides and active clients cause refusal. Remote restore checks
model digest, collation and unchanged target before resuming. Human jobs carry
an expiring/revocable session reference; explicit retry requires fresh owned
write authority and records provenance. Independent-store consolidation remains
blocked until explicit mappings and a reviewed import exist.

The source and target cannot both be writers. Deployment activation checks
source fencing afresh; after any new target writes recovery uses the current
target, never an old dump alone. Memory/process/log/model limits are separate
from database admission and retained source history. Idle HTTP connections own
no permanent model or database connection. A physical VM may host many separately
authenticated user/client profiles. Agent session IDs are namespaced by principal;
source cursor/write authority is session-specific. Authorized team members
share knowledge and can discover/read retained redacted windows/checkpoints.
Immutable publication-team attribution is stored with first input/checkpoint,
separately from uploader authority, and survives author departure. Current team
and project grants govern reading; cancellation/retry remain owner-only. A shared VM key or Herdr session label
cannot identify separate users. Department ACLs require explicit grants, including
for legacy general/global content. Filesystem secrets and administrative tools
remain protected by separate OS/tool permissions. Automatic Herdr user binding
is not part of the verified connector setup.

Final-review reconciliation adds connection-bound canonical commit authority,
independent of later ContextVar changes. Every canonical commit reloads the exact
authenticated credential/session and compares current permissions. Mining's
separate accepted-extraction transaction retains only normalized provider output
and acceptance audit after revocation; worker checks and canonical commits still
prevent application. Remote document preflight includes every joined source and
assertion record; repeatable-read isolates preflight and materialization. The
finite deployment idle-transaction limit now exceeds the default model/embedding
waits, separately from HTTP request deadlines.
Graph/domain results use a single materialized SQL query with a shared count/byte
check and conditional projection. Rejected values become NULL inside PostgreSQL,
before libpq/Python receive them. Native column types and caller order remain
intact. This closes the separate large-single-row gap in server-cursor limits.

### Integration obligations for independent final review

Derive one whole success scenario across static enrollment, client spool, HTTP
ACK and central application, and one recovery scenario across interruption,
accepted output, authority renewal or safe migration resume. Identify assertions
from FR/IC boundaries rather than only repeating unit tests. The coordinator
implements and runs both before convergence. No final readiness claim precedes
that evidence, complete-range review and a fresh full suite. Reviewer-derived
IT058-S01 and IT058-R01 now run in `tests/service/test_integration.py`: populated019
upgrade and scoped spool→HTTP→real fenced runner→REST/MCP; then lost ACK,
accepted-output interruption, session revocation, explicit fresh-authority retry
without repeated inference, and current-target verified backup/restore. Real
systemd/TLS deployment and reference-hardware inference remain rollout evidence.

Final review3 corrections retain target-project write checks for cancellation
and confirm the window UPDATE before queue/audit mutation. Human HTTP sessions
bind the authenticated user and stable uploader UUID; client profiles persist
that UUID across renewal. Namespacing includes it without changing team grants
or machine-key identities. Canonical commits and workers check the original
HTTP-session hash and uploader binding, so renewal grants no implicit job retry.

The populated reference-host rehearsal exposed repeated eligibility subqueries
through source RLS. Migration023 replaces them with bounded keyed invoker lookups;
trust semantics, reader/writer privileges and the15s scoped SQL deadline remain.
The same additive migration introduces the nullable uploader UUID for original022
installations. Original-session comparison permits only that all-NULL addition;
the service and verifier reject incompatible type/null/default/generation drift.

Reference-host process controls prioritize the API (CPU weight200) over serial
background extraction (weight20, nice10, one-CPU quota including CLI children).
This is a process preference, not priority inside shared PostgreSQL or Ollama.
Future shared-model scheduling and queued foreground requests belong to6.10.
