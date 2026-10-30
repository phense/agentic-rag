# Implementation Plan: Local and central knowledge service

## Stable work ID

Issue58 / roadmap6.0 / runtime `RAG-058`. Specification: [spec.md](spec.md).

## Summary and technical context

Keep Python3.13+, PostgreSQL17/pgvector and the current audited gateways. Add a Starlette ASGI service and one HTTP connector instead of replacing storage or adopting Mem0. Pin direct transport dependencies in the project. Existing stdio/local hooks remain compatible; explicit client configuration moves their database/model work to the service.

The service host owns PostgreSQL, Ollama, structured extraction and one supervised worker. Agent hosts own transcript reading, bounded durable upload spool, local compaction handoff and lifecycle adaptation. No wire input is interpreted as a server path.

## Decisions and project gates

| Gate/decision | Evidence and response |
|---|---|
| One engine, audited writes | Reuse `mcp_server.py`, `store.py`, `mining.py`, continuity stores and existing SQL functions. New transport does not reimplement retrieval or extraction. |
| Identity and account method | Static TOML users and machines. Passwords use salted scrypt verifiers; human login issues random expiring opaque sessions. Machine bearer keys use SHA-256 verifiers of generated high-entropy tokens, bind an explicit user and narrow its permissions. No open registration. |
| Request authorization | A ContextVar carries immutable authenticated identity/configuration. `db.connect` applies session-scoped service settings to fresh role-limited connections. Additive RLS policies filter canonical tables, counts and graph joins before evaluation. Legacy connections with no service context retain their grants/behavior. Audit writes carry authenticated actor identity. |
| Definer functions | Chunk/context writer functions need explicit scoped-document checks because SECURITY DEFINER bypasses ordinary RLS. No client supplies SQL/settings or owns a DB connection. Verify these paths independently. |
| No permission by filter | Credentials define allowed read/write domains and exact canonical project scopes (explicit `*` only for trusted unrestricted principals). Project filters intersect these; remote project IDs use lexical normalization, never service-host filesystem/Git discovery. |
| Cache boundary | Cache query vectors only; key service authorization context. No cross-principal result/context cache. Cached client context is owned by endpoint/credential/session and clearly stale offline. Revocation rechecked on every request and before applying work. |
| Durable ingestion | Version1 envelopes carry bounded MiningWindow evidence, stable client session/cursors and idempotency digest. Server namespaces session IDs from authenticated machine/user. Accept rows and queue entries in one transaction, ACK after commit; replay returns the same receipt. |
| Worker authority | Database session advisory lock, held on a dedicated connection through job commits, is the cross-host singleton. Local flock remains an optimization only. One supervised worker drains bounded jobs; no remote hook launches inference. Existing accepted mining batches remain the replay authority. |
| Local persistence | SQLite spool uses durable transactions, protected directory/file modes, finite byte/item caps and no eviction of pending input. Explicit retry/backoff/status. Save a local handoff before any network operation at compaction. |
| Additive migration | New migration021+ adds service state/policies without rewriting existing rows. Current schema020 and deployed019/legacy018 populated fixtures are source rehearsals; earlier compatible schemas require ordered inventory, unknown/newer schemas refuse. |
| Versioning | Protocol1 HTTP clients match protocol1 server; schema capability reports exact migration set. Legacy local stdio remains supported. Release patch is set after dependency PRs merge; no minor bump implied by roadmap6.0. |
| Rollout authority | Only isolated tests/fixtures now. Production transfer, interruption, credentials and cutover require separate authorization. New implementation PR merge also requires approval. |

## Interfaces

See [contracts/service-v1.md](contracts/service-v1.md). Shared dispatch validates arguments against existing tool signatures before invoking business logic. REST endpoints and mounted stateless streamable-HTTP MCP share authentication; `/mcp/ro` exposes only read tools and `/mcp/rw` requires write permission. Legacy stdio proxies to the configured endpoint when in client mode.

Human sessions and machine identities are separate. Policy is loaded from a protected server file per request; revoked/disabled users, machines or credentials fail immediately on the next request. Password login is bounded/rate-limited. Tokens/passwords never enter response diagnostics, logs or example files.

## Data and failure lifecycle

New service tables hold human session token verifiers, owned source windows and stream heads; existing canonical documents/evidence/batches remain authoritative. Ownership keys combine configured machine and user, not an asserted hostname. Namespaced session IDs cannot collide with another machine's same original session ID.

A durable upload transitions `local pending -> accepted receipt -> queued -> applied`. Exact replay is safe at either boundary. Conflicting content or a missing predecessor is409 and retained locally for recovery. Provider failure leaves durable work pending with bounded backoff; worker death releases the database lock and accepted batches resume idempotently. Cancellation is explicit and retains source/receipt/history.

## Upgrade and recovery

Inventory versions/migrations, grants, table counts/hash manifest, queue paths and model identity without writes. Restore backups strictly to a freshly owned isolated DB and compare original rows/grants before migration, then compare preserved rows after migration. Keep local upgrade separate from opt-in remote migration. Remote preflight reports unreadable queued transcript dependencies and required session/source mappings before cutover. Independent-store inventory reports ID/slug/source collisions and refuses unresolved merges; the actual source inventory determines whether consolidation is required.

Fence old workers and writers, restore/verify target, apply ordered migrations, configure server, enroll clients, verify scoped reads/submissions, then switch clients. Never run divergent old/new writers. After new target writes, use target forward recovery/current verified backup; old backup restoration alone is lossy. Legacy runtime code-only rollback is allowed only where new schema semantics remain safe and service writes are fenced.

## Implementation ownership and slices

Coordinator owns all files; independent reviewers are read-only and sparingly delegated on Sol medium/high.

1. `service/auth.py`, `service/context.py`, `service/api.py`, `service/engine.py`, `db.py`, scoped SQL and MCP routing: authentication, enforcement and transports.
2. `service/ingest.py`, `service/client.py`, `service/spool.py`, `service/worker.py`, existing mining/worker/hooks integration: durable evidence, checkpoints and failure recovery.
3. `service/upgrade.py`, CLI/config/install adapters, `docs/13-central-service.md`, deployment examples: compatibility, inventory, verified move and operations.

## Tests and evidence

- Test-first targeted contracts for authentication, protocol mismatch, scope isolation and idempotency; then integration with real PostgreSQL and public synthetic source windows.
- Four clients, one store: scoped counts/search/get/graph/context, RW/RO, credential rotation/revocation, guessed IDs and spoofed fields.
- Real spool/HTTP/queue/worker integration, disconnect/reconnect, retries, provider boundary failure, accepted-batch replay and compaction fallback; assert no acknowledged loss and no duplicate applied batch.
- Populated018/019 upgrade, strict backup/restore, all-original-row/grant comparisons, interrupted migration retry and clean standalone path. Sources with independent stores require collision/mapping rehearsal before consolidation is claimed complete.
- Full existing suite on isolated PostgreSQL; no production DB or private provider calls. Large slices receive1–3 bundled review/test rounds; fix C/H/M and append confirmed Low findings to Issue75.
- Synthetic cold/warm requests and four-client throughput/backlog with CPU/PSS, explicit hardware/model limits. Benchmark4-vCPU/8-GiB class only when that machine is actually tested; no extrapolated SLA.

## Architecture and playbooks

Trust/ownership and durable-ack ordering are modeled in `docs/uml/central-service.md`; findings map to tasks before implementation. As-built reconciliation and independently derived success/recovery integration tests gate completion.

PB-058-01..03 share `docs/13-central-service.md`, owned by coordinator. Installation/enrollment and outage procedures must be ready before handoff; cutover/restore procedures must be rehearsed against the isolated populated fixture before a migration-readiness claim. Development operation DB-058-01 is the isolated database/test runner recorded with exact commands and exit results in `docs/verification/issue58-service.md`; it is required before migration tests. Existing production planner settings remain unchanged.


## Resource requirement added during implementation

FR-012/AC-008 extend S2 admission and S3 deployment/rehearsal. Finite central
storage and backlog limits run through a trusted fixed-aggregate connection;
canonical writes retain scoped roles and the original audited gateways. A
non-blocking global admission lock bounds concurrent growth checks. Exact durable
replay precedes pressure checks; no knowledge/input cleanup is automatic.
Worker authority uses an owner lock plus shared execution pins on every data
connection, fencing replacement inference until surviving old execution exits.
The service checks keeper authority before SQL/commit and returns runner status1
on loss. Linux systemd/model budgets and backup free-space preflight remain S3.

## Team-sharing clarification during final review

The maintainer requires shared IT knowledge and session logs across IT users,
with isolation between departments. User/client identities serve authentication,
audit and collision-free upload cursors; Herdr session names are not ACLs.
Explicit user `session_teams` are inherited or narrowed by machines. First source
or checkpoint admission transactionally writes immutable publication-team/owner/
project attribution. Current team plus project scope permits SELECT of source
windows/checkpoints, without granting cancel/retry/update rights. This preserves
team history after an author leaves. Knowledge uses common department grants.
Bounded paginated REST routes whitelist public log fields and exclude internal
credential references. Standalone and omitted-team owner-only behavior remain.
The in-progress final review3 and full suite were interrupted for this clarified
requirement; validate the updated feature before resuming that final review gate.

Final authority corrections preserve team sharing: cancellation must confirm a
currently authorized window transition before queue/audit changes. Human login
binds the authenticated user to a stable uploader UUID retained per VM/client
profile across token renewal; independent profiles generate different IDs. The
UUID only names upload/continuation state, never grants team/knowledge access.
Workers bind both that profile and the exact revocable login session.
