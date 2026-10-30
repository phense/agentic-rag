# Service protocol1

Every `/v1` request except login carries `Authorization: Bearer <token>` and `X-RAG-Protocol: 1`. HTTPS is required off loopback. Malformed/unsupported versions fail before mutation. Responses use JSON; diagnostics contain stable error codes and no foreign identifiers or database exception text. Max request bytes:1MiB; max source-window text:12,000 characters, at most64 events. Limits are server-side and cannot be raised by callers.

| Method/path | Request | Response |
|---|---|---|
| GET `/health` | none | Liveness only, no corpus/configuration details |
| POST `/v1/login` | username/password, optional stable uploader_id UUID | Opaque token, expiry, uploader_id; verifier stored server-side |
| POST `/v1/logout` | human session | Invalidate that session |
| GET `/v1/capabilities` | authenticated | Protocol1, server/schema versions, tool privileges and limits |
| POST `/v1/tools/{name}` | existing tool keyword arguments | Existing tool JSON result, credential-derived authorization |
| POST `/v1/windows` | version=1, session_id, input_cursor, output_cursor, project, window{ text, events, warnings, synthetic, has_more } | receipt, durable=true, state; exact replay same receipt |
| GET `/v1/jobs/{receipt}` | owner or authorized session team | Bounded visible status; unknown/unauthorized404 |
| POST `/v1/jobs/{receipt}/retry` | Owned blocked/error receipt, authenticated anew | Explicit audited reauthorization; original principal retained; terminal/foreign409/404 |
| POST `/v1/jobs/{receipt}/cancel` | owned receipt | Durable cancellation retaining source/history; no ambiguous applied rollback |
| POST `/v1/checkpoints` | bounded session snapshot/handoff | Owned checkpoint ID after durable persistence |
| GET `/v1/checkpoints/{session}` | owned original client session | Latest owned checkpoint or404 |
| GET `/v1/sessions` | optional before=session_id, limit1..100 (default50) | Visible owned/team sessions, actor, project, created_at and next token |
| GET `/v1/sessions/{session}/windows` | server session ID, optional after=receipt, limit1..4 (default1) | Redacted retained source windows; no internal credential references; bounded512KiB |
| GET `/v1/sessions/{session}/checkpoint` | server session ID | Latest visible team/owned checkpoint or404 |
| GET `/v1/admin/status` | authenticated human administrator | Aggregate service health/queue and configured identity labels, never credentials |
| GET `/v1/openapi.json` | authenticated | OpenAPI3 description of implemented routes/schemas |

Remote MCP mounts `/mcp/ro` and `/mcp/rw` use the same bearer identity. Write-capable configuration never makes the RO endpoint register write tools. Remote capabilities are negotiated through the authenticated HTTP contract; MCP retains its own transport-version handshake. Legacy stdio stays compatible and can proxy through the same HTTP client.

A source event contains `source_id`, `role` (user/assistant/unknown), timestamp (timezone-aware or null), text, offset and complete. The server verifies fragments against the window text and retains exact evidence identities in its authenticated session namespace. It does not trust a caller-supplied machine/role override. Oversize, malformed or conflicting windows fail without cursor advancement. A cursor-only window with empty text/events acknowledges consumed structural or tool-only records without an extraction call; unchanged cursors fail. Out-of-order windows409 remain pending in the client spool.

The server cursor advances on durable acceptance; processing status advances independently. Upload ACK means recoverable queued input, not completed extraction. Client timeout after server commit is recovered by exact replay. Authorization failure retains the local pending entry and reports blocked access. Buffer overflow is visible; pending input is never evicted. No source retention cleanup is introduced in this release.

Configuration uses users with scrypt password verifiers and read/write domain/project lists, machines with stable ID, bound user, label, enabled flag and key verifier IDs. Omitted permissions deny access. Narrow machine policy intersects user policy. Explicit `*` grants unrestricted scope only when configured by the operator. Human admin status does not imply unrestricted knowledge access. Revocation reload semantics: next request and next job application use the latest policy.

The service refuses startup if its required migrations, scoped-table RLS/policies,
old-row UPDATE guards or non-bypassing reader/writer roles are missing. Every new
scoped engine connection repeats this check before a knowledge query, so disabling
protection after startup also fails closed. Operators migrate explicitly; starting
the HTTP process never migrates an existing installation.

Remote context treats project identifiers lexically, including checkpoint fallback
and rendering. It never resolves a client project against service-host Git/files.
Operator backup/provider diagnostics appear only as stable status codes in remote
knowledge context; detailed local warnings remain available to the operator. Audit
actors encode identity type (`service:human:<user>` or
`service:machine:<user>:<machine>`), independently of the bounded edge-origin enum.

Only POST is supported on the stateless JSON MCP mounts. GET/SSE and other methods
return405 before reserving shared request capacity. The audit-actor trigger must
also be enabled before service access. Nested gateway writes retain the verified
transport actor; edge origins keep their existing enum.

Client configuration selects `[service] mode="client"`, `url`, `token_file` and
`spool_dir`; the default mode remains `standalone`. Hooks capture local state and
launch only the uploader in client mode. The stdio connector forwards existing
tools through REST, retaining the RO registration boundary. Claude, Codex,
Antigravity and OpenCode lifecycle adapters share this connector.

The owner-only SQLite spool uses FULL synchronous transactions. Its16MiB logical
input budget covers raw local source snapshots, pending JSON and checkpoint
fallbacks; source snapshots reserve1MiB for upload production. SQLite journals,
indexes and bounded context/receipt caches add disk overhead. Pending input is
never evicted. Oversize or changed source files require explicit local recovery;
retain the original file. Local raw snapshots stay private; only redacted windows
cross HTTP. No automatic source/history cleanup is introduced.

Source capture finishes before hook success. Window/cursor and checkpoint/fallback
transactions are durable locally before upload. Uploads use bounded attempts and
retry/backoff;400-class authorization/conflict failures stay blocked until explicit
retry. Startup displays pending/blocked counts, stale-cache markers and local
continuation state. The central serial worker holds a dedicated database advisory
lock across job commits and orphan recovery. Source and deferred embedding jobs
recheck credential revision and current permissions before application/commit.


Resource admission uses a shared database gate before service writes. Defaults
under `[service]` are `max_database_bytes=8589934592`,
`min_free_bytes=2147483648`, `max_pending=1000`,
`max_pending_per_owner=100` and `max_pending_bytes=67108864`.
The owner limit counts non-terminal source windows for the authenticated machine
or human namespace; the global pending count includes other queued jobs. Backlog
pressure returns429, database/free-space pressure507, and an unavailable storage
check503. Existing exact window replay returns its durable receipt even under
pressure; reads, job status, cancellation and logout remain available. Limits do
not delete evidence or history. Terminal history consumes the database budget and
requires an explicit operator retention/archive decision. Remote PostgreSQL needs
an explicit accessible `storage_path` on its shared storage mount; otherwise
storage checks fail closed. Legacy standalone writes retain their existing path.

Every live worker data connection holds a shared execution pin. A replacement
owner must acquire the exclusive execution pin before orphan recovery. The keeper
is checked before queries, application and commits; lost authority exits the
central runner with status1. Thus loss of only the keeper or parent connection
cannot overlap a still-running source inference on another connection. Application
reuses any already accepted batch after safe recovery. Cancellation checks both
the receipt and the authoritative applied mining batch under the window lock;
terminal cancelled/applied states cannot be resurrected by failure cleanup.

Diagnostic files rotate at1MiB with three backups and8KiB records. Detached
children use these bounded diagnostics instead of raw append-only stdout/stderr
files. The client retains at most64 recent health partitions,64 context entries
and256 receipts; pending evidence/cursors are separately bounded and never evicted.

Authenticated principals retain the credential revision from their verified policy
snapshot. Deferred jobs carry that original revision; reloading a changed policy
cannot rebind them to a replacement key/password that never authenticated their
request. Execution reloads policy to verify the recorded revision and current
rights. Deferred embedding checks storage before inference and again before
commit, alongside credential revalidation.

Capacity/storage pressure is a retryable worker condition, separate from invalid
input or provider failures. Accepted jobs remain pending with a60s backoff and do
not spend processing attempts; source receipts expose a blocked stable code. Any
already accepted extraction is reused after pressure clears. Repeated transient
write contention must not exhaust a durable job into a terminal error.


Human jobs also retain the exact authenticated session hash. Logout, expiry,
password change or disabled accounts block inference/application/commit; renewed
login never silently adopts old jobs. Explicit owned receipt retry records new
current authority, retains the original reference and still rechecks accepted
output scope. Retry cannot undo applied knowledge or revive cancelled input.
Idempotent cancellation creates no further audit rows after the first transition.
Public job status exposes only allowlisted stable codes. Diagnostic record limits
count UTF-8 bytes including timestamp/newline.

Remote document/graph/domain materialization has a512KiB/1,000-row safety budget;
large legacy document metadata/body is checked in SQL before loading it. Graph
rows use server cursors. Oversize reads return413 `result_too_large`; standalone
reads retain their prior contract. Process, PostgreSQL, model and filesystem
limits remain operator deployment obligations, documented in the central guide.

Session teams are explicit `session_teams` ID lists (max16) on users. Machines
inherit that list unless a narrower list is supplied; no caller-supplied team or
Herdr name is trusted. A session's first durable input/checkpoint publishes an
immutable owner/project/team record in the same transaction. Team read visibility
requires current membership and project permission; it survives the original
author's departure. Source cursors and canonical continuation writes remain
namespaced by uploader, so colleagues can observe without colliding or gaining
cancel/retry authority. Knowledge sharing uses the team's common domain/project
grants independently. Omitted session teams preserve owner-only session access.
Team routes use the same SQL pre-materialization budget and snapshot as other
bounded reads. They publish source text/events and checkpoint/handoff, never the
job's credential revision/session hash. Local raw transcripts are not uploaded
by these routes.

Human login binds a stable uploader UUID to the authenticated session record.
Omitted UUIDs are newly generated, so independent first-time VM/client profiles
do not share raw session IDs. Re-login supplies the same uploader UUID, retaining
namespace but not old bearer authority; workers verify the exact session and
uploader reference. The CLI persists an owner-only uploader identity file; keep
it across renewal and use a different file on another VM/profile. The UUID is a
namespace selector, never a domain/team permission. Unbound legacy HTTP sessions
fail closed and require login. Machine-key namespaces remain unchanged.
Cancellation requires current write authority for the receipt's project and a
confirmed window UPDATE before queue/audit transition in the same transaction.
