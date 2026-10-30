---
id: C-058
title: Operate a local or central knowledge service
type: task
doc_id: standalone-central-service
readers: [operator]
status: reviewed
version: 0.6.10
depends_on: []
assets: []
last_reviewed: 2026-10-30
summary: Upgrade an existing store, enroll isolated clients, and recover durable input safely.
---

# Operate a local or central knowledge service

This guide is for the Linux operator who owns PostgreSQL and the agent runtimes.
It covers version 0.6.10. Local operation remains the default. Central operation
moves storage, retrieval and queued inference to one server; each client keeps a
private upload spool and compaction handoff. All clients use the same engine.

Writing scope: medium, one operator guide. PB-058-01..03 are system playbooks
owned by the repository maintainer, required by [Issue58](https://github.com/phense/agentic-rag/issues/58).
They must be reviewed and rehearsed before a production operation. Last edited:
2026-10-30. Review and rehearsal evidence: [verification record](verification/issue58-service.md).
The examples are deployment inputs. An authorized reference-host rehearsal has
deployed them against a verified copy; existing installations change only through
an explicit operator action.

## Before starting

Use Python 3.13+, PostgreSQL17 with pgvector, matching embedding model/digest,
`pg_dump`, `pg_restore`, and this checkout's `rag` executable. Source versions
0.6.0–0.6.10 and known schema prefixes018–023 are recognized; populated018/019
have explicit upgrade rehearsals. Other sources require a reviewed migration.

Choose actual paths for `source.toml`, `server.toml`, `client.toml`, private
`/owned/upgrade/` artifacts, the service account and the tailnet HTTPS name.
Commands below run as the relevant file/database owner. Configurations and keys
must be owner-only, mode0600. Keep dumps/manifests private: they contain knowledge
and operational metadata. An operator backup rehearsal requires permission to
create and remove its own temporary verification database on the source cluster.

Before production mutation, obtain the maintainer's approval for the named
installation and maintenance window. Stop its writers through the installation's
existing service manager. Existing binaries do not honor the new worker lock.
A PR merge grants no production migration authority.

## Terms

| Term | Meaning |
|---|---|
| Standalone | Existing local database, hooks and stdio MCP; no service account required |
| Server | One authenticated API and one serial worker on the canonical database |
| Client | Hooks/stdio proxy with HTTP access and no PostgreSQL or inference requirement |
| Spool | Private SQLite input awaiting durable server acceptance; never evicted |
| Receipt | Server-owned identifier returned only after input and queue commit |
| Applied | Knowledge application completed, distinct from input acceptance |
| Fence | Database read-only default plus worker locks during a controlled move |
| Manifest | Private backup hash, original row/ACL/sequence/model integrity evidence |
| Forward recovery | Recover from the current target so post-cutover writes survive |

## Supported versions and staged upgrades

| Client/runtime | Server or database | Supported behavior |
|---|---|---|
| 0.6.0–0.6.9 existing local adapters | Their existing local schema | Remains local until explicitly upgraded; cannot use the new HTTP contract |
| 0.6.10 standalone | Schema023 | Local CLI, hooks and stdio MCP; no network account required |
| Known 0.6.0–0.6.10 source, schema018–023 | 0.6.10 upgrade operator | Preflight and verified additive upgrade; populated018/019 rehearsed |
| 0.6.10 client, protocol1 | 0.6.10 server, schema023 | REST, stateless JSON MCP, or local stdio proxy; server validates all required authorization policies |
| Any other remote combination | Unadvertised protocol/schema | Unsupported; check capabilities and upgrade before retrying |

Every REST client sends `x-rag-protocol: 1`. HTTP426/`unsupported_protocol`
requires an updated client, not repeated retries. Missing schema security causes
startup refusal or503; an operator must finish the verified migration. OpenAPI
includes source/checkpoint request models, receipt status codes and pagination.
Model validators also enforce evidence/cursor relationships beyond JSON Schema.

Provision the upgraded server on a verified copy first. Enroll and test one
0.6.10 client, then the remaining clients, including their hooks and stdio proxy.
For the eventual canonical move, stop old writers and follow PB-058-02; an old
client must not continue writing the old store after cutover. Upgrading a local
installation follows PB-058-01 without any network enrollment.

Protocol1 has no announced retirement. A future replacement must publish its
support matrix, migration instructions and retirement notice in the release
notes and tracking issue before retirement. Operators explicitly schedule that
upgrade; a patch must not silently disable the advertised protocol. Only the
combinations above are currently tested; a future protocol is not promised.

## PB-058-01: Install, upgrade and enroll

Use this playbook to keep an existing installation local or add a central service.
For a move between machines, finish the inventory below, then use PB-058-02.

### Inspect the existing installation

1. Record each VM's runtime version, configuration path, agent hook/MCP commands,
   domain/project permissions and database connection target. Record running and
   scheduled writers, pending local transcript paths, and embedding model identity.
2. Write a private inventory for each distinct store:

   ```sh
   rag service --config /owned/source.toml inventory --source-version 0.6.3 \
     --identities --output /owned/upgrade/source-inventory.json
   ```
3. Run the non-mutating plan:

   ```sh
   rag service --config /owned/source.toml preflight --source-version 0.6.3 --mode local
   ```

Expected: `supported=true` and a known schema. Resolve unknown versions before
continuing. For several independent stores, run `rag service collisions
/owned/upgrade/a.json /owned/upgrade/b.json --output /owned/upgrade/collisions.json`.
Several stores require explicit identity/project/source mappings and a separately
reviewed import. This release reports collisions and refuses automatic merging;
never concatenate dumps. Several VMs already sharing one database need one inventory.

### Upgrade the local store

The following step changes schema and briefly fences returning old writers.
Have approval and the stopped-writer inventory before `--apply`.

1. Stop all known writers and close other connections to the named source.
2. Apply the additive upgrade with an exclusive new backup path:

   ```sh
   rag service --config /owned/source.toml upgrade --source-version 0.6.3 \
     --dump /owned/upgrade/local-20261029.dump --apply --writers-stopped
   ```
3. Check `restore_verified=true` and `original_rows_unchanged=true`; run `rag
   service --config /owned/source.toml status` and the existing stdio RO/RW smoke
   tests before restarting writers with the new executable.

Expected: original rows, permissions and history survive; pending migrations
commit together only after comparison. Keep the dump and `.dump.manifest.json`.
A failed transaction rolls back schema and releases the normal read-only fence.
After a killed process, inspect the database default and manifest before retrying;
repeat with a new dump path, never overwrite a proof. If a retained read-only
source is intentional, follow PB-058-02 instead of restarting old writers.

For a clean installation, use the existing `rag init-db` procedure, then check
`service_ready=true`. Standalone configuration needs no `[service]` section.

### Configure the server and clients

1. Copy [server settings](../deploy/central-service/server.toml.example) and
   [static policy](../deploy/central-service/auth.toml.example) to the chosen
   private configuration paths. Set a distinct client identity for each
   user/VM security profile and explicit domains/logical projects. Several
   identities can run on the same VM; each is bound to one user. User and client
   permissions intersect.
2. Generate a separate key per client identity and a human password verifier:

   ```sh
   rag service key --id vm1 --output /owned/vm1.key
   rag service password
   rag service check-policy --file /etc/agentic-rag/auth.toml
   ```

   Put only printed verifiers into policy. Deliver each0600 key file through the
   organization's approved secret channel. `password` prompts without echo.
3. Create the client configuration on its VM:

   ```sh
   rag service client-config --url https://rag.example.ts.net \
     --token-file /owned/vm1.key --spool-dir /owned/rag-spool \
     --output /owned/client.toml
   ```
4. Set `AGENTIC_RAG_CONFIG=/owned/client.toml` in each hook and stdio MCP process
   environment, retaining both existing RO/RW registrations. Test Claude, Codex,
   AGY or OpenCode with its existing installed adapter. The same client accepts
   `http://127.0.0.1:8765` for a local service.

Expected: client hooks stage input locally and spawn only the uploader. They
never run mining against a remote queue. Project values are logical identifiers;
use the policy's exact normalized path, even when VM directories differ.

### Share within teams and separate departments

One shared VM key represents one configured user; it cannot distinguish several
Herdr users. Give each user a protected client configuration/key, or their own
human login. Set the matching `AGENTIC_RAG_CONFIG` for that user's hooks and MCP
processes. Static provisioning supports this; automatic Herdr account mapping
is not installed or verified. A Herdr session name is not authentication.

Give every IT profile the same knowledge scopes and `session_teams=["it"]`;
use `session_teams=["accounting"]` for bookkeeping. Personal credentials identify
changes, not private knowledge silos. Machines inherit the user's session teams;
an explicit machine list can only narrow them. Team publication is retained when
an author leaves. Removing a reader's team/project grant takes effect immediately.

Each AI session has a distinct namespaced ID to prevent cursor/continuation
collisions. Colleagues discover shared logs with `GET /v1/sessions`, then read
`/v1/sessions/{session_id}/windows` or `/checkpoint`. These routes expose bounded
redacted retained input, not complete local raw transcripts or credential
references. Use returned pagination tokens; windows default to one per page.
Automatic hooks resume their own session; shared read access does not grant
cancellation, retry or overwriting another session. HTTP requests share capacity; no permanent model or database session
is reserved per agent session. Heavy inference is centrally queued. More than
eight simultaneous active requests may receive429 and require bounded retry;
the40-connection rehearsal does not establish20-agent model throughput.

Use explicit department allowlists. For example, IT profiles can read/write
`sysadmin` with their approved projects; accounting profiles can access only
their bookkeeping domains/projects. A prompt, hostname or requested filter
cannot grant IT access to accounting. Share knowledge within IT; expose
interdepartmental common domains only after review. Existing IT records under `general/global` must
not automatically become shared when another store is imported. Same-named
domains/projects across stores require a reviewed mapping before import; the
current importer deliberately refuses automatic multi-store consolidation.

Keep service credentials in each department's local protected environment.
RAG authorization controls retrieval, not command execution or filesystem access.
Separate OS accounts/containers/VMs and tool privileges are required where users
must not read one another's token or credential files. Named Herdr sessions under
one shared administrator account do not create that boundary. A bookkeeping
agent can still know generic IT concepts from its model; administrative actions
must be restricted through its actual tools and operating-system permissions.

### Start and verify the central service

For a headless Claude subscription worker, run `claude setup-token` in the
operator's terminal and deliver the result through a protected secret channel.
Store `CLAUDE_CODE_OAUTH_TOKEN=<token>` in root-owned0600
`/etc/agentic-rag/claude-oauth.env`. The worker unit loads this optional file at
every start; enable the unit for boot. A service/VM restart preserves the file.
Token expiry or revocation still requires replacement and a worker restart.
Do not copy another workstation's refresh-token store or commit this file.

1. Provision a dedicated OS/database owner, pgvector and non-bypassing
   `rag_reader`/`rag_writer` roles using the existing installation procedure.
   Match the source pgvector version and preload `vector` in the dedicated
   PostgreSQL instance. A privileged bootstrap must create the extension as the
   restore operator; the operator needs ownership for restored extension comments,
   while reader/writer roles remain unprivileged. Do not grant them superuser.
   Preserve the original database owner role and named ACL grantees, including
   default-privilege owners. If the OS account differs, set `PGUSER` to that
   database owner in both unit overrides and in operator commands, and add its
   exact peer/HBA mapping. Arbitrary role renaming is not an automatic migration.
   Configure local peer mappings from [pg-ident](../deploy/central-service/pg-ident.conf.example)
   and [pg-hba](../deploy/central-service/pg-hba.conf.example); preserve operator
   access. Database/inference ports stay private.
2. Review and install the [API](../deploy/central-service/agentic-rag-api.service)
   and [worker](../deploy/central-service/agentic-rag-worker.service) units at
   `/etc/systemd/system/`, replacing `/opt/agentic-rag`, account and hostname
   parameters. Start one API and one worker in the authorized window. For an
   isolated foreground rehearsal use:

   ```sh
   rag service --config /etc/agentic-rag/server.toml serve \
     --auth-file /etc/agentic-rag/auth.toml --allowed-host rag.example.ts.net
   rag service --config /etc/agentic-rag/server.toml worker
   ```
3. Configure Tailscale HTTPS serving to the loopback API, restricted by tailnet
   access rules. Use the approved tailnet configuration for this host. A direct
   HTTPS proxy must preserve the authenticated Host and correctly convey HTTPS;
   untrusted forwarding headers are disabled in the supplied CLI. With Tailscale
   Serve's loopback upstream, the API accepts local HTTP. Do not enable Funnel.
4. From every client, query capabilities, perform one permitted read/write and
   one forbidden read/write, then verify that only its own receipt/checkpoint is
   visible. Verify RO MCP rejects mutation. Inspect `service status` on the server.

Expected: all clients share one store with separate authority. Health alone
proves process availability; it does not prove model readiness or client scope.
Unknown/missing security migrations refuse startup.

Human login uses `rag service login --url https://rag.example.ts.net --username
operator --uploader-file /owned/this-vm.uploader --output /owned/session.key`;
create a client configuration referencing that token. Keep the0600 uploader file
when renewing a token; use a new uploader file for each other VM/client profile.
If omitted, its path defaults to the token path plus `.uploader`. API-only login
returns a generated `uploader_id`; send that ID again on renewal. It separates
cursors/checkpoints, grants no permissions and never restores revoked authority.
Sessions expire after8h. `rag service --config /owned/human.toml logout`
revokes that session and its uncompleted jobs. Disable a machine or remove its
key verifier in the0600 policy to revoke it; subsequent requests and job
application recheck authority. Policy replacement must retain correct ownership.

## PB-058-02: Move, restore and recover

Use this playbook for one inventoried canonical store. Resolve remaining local
transcript jobs on the source before moving; remote preflight refuses them.
Reserve space for source, dump, verification restore and target separately.

1. Run `preflight --mode remote` using the source configuration. Require
   `ready=true`, no unresolved paths, matching embedding model/digest and a
   private, empty target database with compatible collation and roles.
2. Stop source writers with approval; run:

   ```sh
   rag service --config /owned/source.toml prepare-cutover --source-version 0.6.3 \
     --dump /owned/upgrade/move.dump --apply --writers-stopped
   ```

   Preserve `move.dump`, `move.dump.manifest.json` and `move.fence.json`. The source
   remains read-only. Persisted role overrides that could defeat the default are
   rejected. Returning trusted old binaries fail writes; this operational fence
   does not restrain a malicious database administrator.
3. Transfer all artifacts privately; restore into the confirmed empty target:

   ```sh
   rag service --config /owned/target.toml restore-target \
     --dump /owned/upgrade/move.dump \
     --manifest /owned/upgrade/move.dump.manifest.json --apply
   ```
4. Freshly verify the source still has its read-only default and no writers;
   check target integrity/status and scope/model smoke tests. Switch client
   configurations only after those checks. Keep the source fenced.

Expected: strict restore comparison succeeds, then additive migrations preserve
original hashes, grants and history without re-extraction or re-embedding.
Custom object owners require a reviewed explicit mapping. The import never
silently replaces a populated target.

### Interruption and recovery decisions

| Observed state | Operator action | Completion evidence |
|---|---|---|
| Backup/import failed before target acceptance | Keep source fenced; inspect private diagnostics and dump hash; retry matching unchanged target with `restore-target ... --apply --resume` | Same original rows; no intervening target writes |
| Source fence retained; target never accepted writes | Stop target, verify its unchanged manifest, then restore source database default to the saved `prior_read_only` value with the database owner | Exactly one writer, original source hashes verified |
| Target accepted any new knowledge/input | Stop both writer sets; take `verified-backup` of the current target and recover forward from that target | Current target input/knowledge preserved; original old dump alone is insufficient |
| Source/target drift, unknown schema or mismatching model | Stop before switching clients; preserve both stores, manifests and logs for the maintainer | Reviewed reconciliation, no guessed overwrite |

To clear a retained fence only after the applicable row above: the database
owner runs `ALTER DATABASE "actual_name" RESET default_transaction_read_only`
when `prior_read_only` is null, or restores its exact prior setting. Recheck a
fresh connection. Do not reopen source writers while the target is active.
A process killed after commit may leave an already-complete upgrade; inspect
status and preservation proof before retrying. Interrupted restore is one
transaction; a completed restore followed by failed migration can resume only
while its original contents still match.

`verified-backup --source-version 0.6.10 --output /owned/upgrade/current.dump`
creates an independently restored proof. Scheduled `rag backup` has finite
retention and a space check in server mode, but does not perform that full
integrity rehearsal. Retain at least one independently verified backup and
repeat restore verification after model, schema, permission or storage changes.

## PB-058-03: Outage, pressure and compaction

Use this playbook when hooks report stale/offline context, blocked uploads or
job status that has stopped advancing. Preserve the spool and raw transcript.

1. Inspect `rag service --config /owned/client.toml spool` and server `status`.
   Check network/TLS/authentication before retrying. A durable receipt means the
   server owns the input; it can still be queued, blocked, applied or cancelled.
2. Restore network/provider capacity or storage reserve. Run `spool --flush`;
   use `spool --retry-blocked --flush` only after correcting the reported cause.
   Exact replay returns the existing receipt. Conflicting cursors require
   inspection of the original stream; never invent a successor cursor.
3. For an owned blocked/error server receipt after deliberate credential renewal,
   run `rag service --config /owned/new-client.toml job-retry RECEIPT`. This
   explicitly records new authority and preserves the original principal.
   Applied/cancelled/foreign receipts refuse retry. Cancel is not a rollback of
   applied knowledge.
4. Trigger the installed manual/automatic compaction adapter offline, confirm
   its local handoff, then resume and flush after reconnection. Confirm the
   final tail reaches an owned receipt and stale context becomes current.

Expected: unacknowledged input remains in the private spool; accepted server
input remains available for replay/recovery. The spool is partitioned by endpoint
and credential. Keep the old credential/configuration artifacts when rotating;
new credentials do not silently adopt old pending uploads. If pending input
belongs to a permanently revoked partition, preserve it and ask the maintainer
for an explicit reviewed replay plan. No automatic rebind is provided.

## Operating limits and stop conditions

| Resource | Default / action |
|---|---|
| API | One process, eight active requests,64 transport slots,30s keepalive,1MiB request body/5s receive deadline; idle MCP SSE rejected |
| Remote reads | k≤50, graph depth≤3,512KiB materialized document/graph/domain budget and1,000 graph/domain rows; oversized results fail explicitly |
| Client |16MiB logical pending/raw/handoff budget;2,000 source/cursor entries;256 receipt and64 context records; never evict pending input |
| Central writes |8GiB database budget,2GiB free-space reserve,1,000 pending jobs,100 pending source windows per owner,64MiB pending source payloads; explicit429/507/503 pressure |
| Worker | One database-fenced inference worker; retry with backoff; SIGTERM stops after current job; process group killed after330s by example unit |
| Logs | Four1MiB worker/client files;8KiB UTF-8 records; namespace journal64MiB persistent/16MiB runtime in supplied example |
| Backup | Finite configured counts, conservative free-space check before dump/restore rehearsal; unique private artifacts; previous backups survive pressure |

Canonical writes recheck the original credential, session and permissions before
each commit. A logout, expired session, rotated key or changed scope rolls back
an in-flight synchronous write. Already accepted extraction is retained for an
explicit authorized retry; retaining that result does not apply it to knowledge.
Remote document budgets include joined source records and assertion data, with
one database snapshot for checking and reading the result.
Graph and domain queries check their row/byte budget inside the same SQL
statement and suppress oversized values before sending them to the API process.
Manual `spool --flush` still uploads previously staged input when a fresh source
cannot be staged; its status records `source_staging_failed` for that source.

Review [PostgreSQL](../deploy/central-service/postgresql.conf.example),
[Ollama](../deploy/central-service/ollama.conf.example) and
[journal](../deploy/central-service/journald-agentic-rag.conf) limits before use.
The PostgreSQL example allows30min of idle transaction time: the configured
extraction may take300s, and one256-input embedding page may need eight120s
HTTP rounds. Keep this finite and reassess it when changing provider or batch
limits. An idle database transaction during inference is separate from an idle
HTTP connection; the API's30s keepalive and5s body deadline still apply.
Database budget is an admission limit, with transaction/WAL/index overhead; it
is not a filesystem quota. PostgreSQL `max_wal_size` is not a hard WAL cap.
Monitor free bytes/inodes, WAL/replication slots, pending jobs, backups and RSS/PSS.
Use storage-volume quotas or a dedicated volume for a final filesystem bound.
Never delete knowledge, accepted windows or pending spools to satisfy a cap.

The API has CPU weight200; the serial background worker has weight20, nice10
and a one-CPU quota. These controls cover the worker and its CLI children,
while PostgreSQL and shared Ollama work require separate measured budgets.
They prioritize current-work retrieval over Python/CLI extraction; they do not
establish priority inside a shared embedding service. The broader queued-client
and model-scheduling extension is tracked in roadmap6.10 / Issue68.

The example API/worker memory caps are384MiB/1GiB; database, reranker and model
processes require their own measured budgets. Ollama's2GiB example can reject
an oversized model; it is not proof that a particular model fits. Before buying
or sizing a4-vCPU/8-GiB host, measure actual model residency and cold/warm load.
The recorded40-connection API rehearsal used synthetic capability/domain requests,
separate from populated retrieval and real-model extraction tests. The reference
host completed30synthetic source jobs, including recovery after a killed worker.
With extraction active,12populated searches and12context calls all succeeded;
search median5.039s and context median1.700s. These finite measurements do not
prove day-long stability or20simultaneous expensive queries. The hook connector's
one-second context deadline can still select its stale/offline fallback during
such bursts. The measurements and remaining limits are in the verification record.
Stop fresh writes
on pressure, preserve durable input and provision reviewed capacity before retrying.

Maintenance triggers: repeat review/rehearsal after schema, policy, transport,
model, hook, service-manager or storage-layout changes. Escalate with versions,
receipt IDs, sanitized status codes, counts, manifests and the observed failing
command; retain private artifacts locally and exclude credentials/raw content
from public issues.


Schema023 also adds the nullable human uploader UUID to installations using the
original schema022. The operator verifies every original session field while
allowing only that new all-NULL field; other row changes still refuse the
upgrade. Both preservation checks and service startup require the field to
remain a nullable UUID without a default or generated value. Existing pre-profile
login rows remain in history, but those users
must log in again with a stable per-VM uploader profile. Machine keys are
unchanged. Apply pending migrations once; never replay022 manually.

## Dashboard in 0.6.12

The additive [dashboard](15-dashboard.md) uses schema025 and the same service/queue.
The measurements and version matrix above describe their recorded release; use
the dashboard guide for current bootstrap, browser access and upgrade prerequisites.

## Request tracing in0.6.13

The additive [request tracing capability](16-request-tracing.md) uses schema026.
Upgrade a populated025 service through the same verified backup/restore and writer
fencing procedure before starting the new API. It retains bounded operational
metadata separately from canonical knowledge/audit and preserves accepted-job
origin IDs after metadata pruning. Existing protocol1 clients can ignore its
new response headers. Code rollback can keep the additive tables and new writes.
