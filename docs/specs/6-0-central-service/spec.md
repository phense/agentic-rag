# Feature Specification: Local and central knowledge service

## Stable work ID

- Roadmap ID: **6.0**, canonical [Issue58](https://github.com/phense/agentic-rag/issues/58).
- Runtime work ID: `RAG-058`; feature inventory ID: `F-058`.
- Status: Specified; implementation and rollout remain separate gates.
- Source request: centralize 3–4 agent VMs on one affordable service, preserve local operation and upgrade existing installations without losing information. Code changes use PRs.

## User scenarios

### US-001: Keep an existing installation local (P1)

An operator upgrades its runtime and schema while preserving the original knowledge, evidence, permissions, queues and active session history. Existing stdio integrations continue to work; using the new loopback connector is optional.

### US-002: Share one service from four machines (P1)

An operator enrolls independently revocable machines and human accounts. Agents read and write only their configured domains/projects through the same client used on loopback. Clients need neither database credentials nor inference runtimes.

### US-003: Continue through network failure and compaction (P1)

A client durably captures source windows and handoffs before transmission. Hooks finish promptly while offline. Reconnection delivers the final tail exactly once; an unauthorized department cannot access the session even when it guesses its original ID. Authorized IT colleagues can read the same team logs; each uploader retains distinct cursor/write authority.

### US-004: Move and recover an existing store (P1)

An operator inventories supported source versions, takes a verified backup and rehearses restore and additive migrations on an isolated populated copy. Explicit cutover fences old writers. A failed cutover resumes safely or recovers without silently losing writes accepted after cutover.

## Functional requirements

- FR-001: Retain one canonical knowledge engine and audited write boundary across local CLI, stdio MCP, REST and remote MCP. Preserve both MCP privilege levels.
- FR-002: Publish versioned knowledge/context/checkpoint/source/job/admin contracts and compatibility negotiation; reject unsupported protocol/schema combinations before side effects.
- FR-003: Authenticate stable machine IDs separately from human/service users. Static provisioning is sufficient. Human password login must produce expiring, revocable sessions bound to a stable uploader profile that survives token renewal and differs across VM profiles; machine keys must be individually revocable.
- FR-003A (maintainer clarification2026-10-29): A VM may run20+ independent AI sessions for different users. Provision separate authenticated user/client profiles on that VM; a shared VM key or asserted Herdr session name is not a user identity. Namespace source/checkpoint cursors by authenticated principal and agent session to avoid collisions, not to create private IT knowledge silos. Explicit team membership grants shared read access to retained session windows/checkpoints; all IT members receive the IT knowledge scopes and IT session team. Herdr names never authorize access. Document explicit per-user connector configuration and the separate OS/tool credential boundary; automatic Herdr account binding is not claimed.
- FR-004: Derive permissions only from verified credentials. Enforce domain/project scope before reads, graph traversal, writes, counts, context, job/source lookup and exports. A filter, hostname or RO environment flag cannot increase permission. Revalidate credentials on every request.
- FR-005: Keep verifier-only server credentials, protected client secrets and bounded redacted diagnostics. Remote transport requires TLS; localhost requires no Tailscale or external account. Database and inference ports remain private.
- FR-006: Transfer bounded, versioned evidence windows with source identities, timestamps, roles, input/output cursors and authenticated client/session ownership. Duplicate content replay is idempotent; conflicting replay and out-of-order windows are explicit recoverable errors.
- FR-007: Persist a bounded client spool before upload; delete an entry only after durable server acceptance. Never evict unacknowledged entries. Expose pressure, blocked/revoked uploads, retry/backoff and stale cached context. Preserve a local handoff before manual or automatic compaction.
- FR-008: Process accepted work centrally with a database-enforced singleton, durable state, bounded jobs/provider calls and crash recovery. No client-spawned mining worker may drain the remote queue. Accepted model batches retain the existing replay/application guarantees.
- FR-009: Provide non-mutating source inventory, supported-version checks, strict backup/restore verification, additive local upgrade and explicit remote-cutover procedures. Preserve original rows, grants and evidence; model-compatible moves require no re-extraction/re-embedding.
- FR-010: Inventory independent stores before consolidation. Report collisions and required mappings without modifying sources. Refuse unresolved collisions and unsafe imports; never silently concatenate dumps or split the canonical store by provider.
- FR-011: Expose bounded health/status/version information and operator procedures for installation, enrollment, revocation, outage, backup/restore and forward recovery. Production rollout is a separate authorized operation.

- FR-012: Support30–40 persistent connections without one model, worker, DB session or durable row per idle connection. Bound request bodies, active work, client spools/caches, central backlog, database budget, free-space reserve and diagnostics. On pressure reject new input explicitly; never evict acknowledged knowledge or unacknowledged input. Measure repeated requests, connection churn and outage/recovery; distinguish retained knowledge from leaks.

## Acceptance criteria

- AC-001: Existing stdio contract tests pass for all 18 RW/10 RO tools; a populated 0.6.3/schema019 installation and schema018 fixture upgrade without changing original rows or grants. A clean installation also succeeds.
- AC-002: Four independently authenticated clients concurrently read and submit work into one store. RO mutation, foreign domain/project/graph/context/count access, spoofed machine identity, guessed receipts and revoked credentials disclose no foreign data and make no unauthorized changes.
- AC-002A: Characterize24 AI sessions on one logical host with distinct prompts and two independently authenticated departmental users, deliberately overlapping raw session IDs. Preserve each accepted window/job/checkpoint and deny cross-department receipts and foreign IT knowledge through get/search/context. Allow bounded429/backoff; report the workload separately from real-model throughput. Before any IT/accounting store consolidation, explicitly classify/map existing domains including `general/global`; no automatic department-wide sharing.
- AC-002B (maintainer clarification): Two separately authenticated IT colleagues on any configured VM can discover/read the same retained IT session logs, checkpoints and knowledge; accounting cannot. Keep uploader cursor/checkpoint mutation and job cancellation/reauthorization distinct from team reading. Retained publication-team history survives author removal; current team/project revocation takes effect on the next request. Return bounded redacted source records without internal credential references. Session labels never grant authority.
- AC-003: Disconnect/reconnect, duplicate/conflicting/out-of-order submissions, provider failure and worker death preserve acknowledged work and prevent duplicate applied batches. The same original session ID on two machines yields distinct server sessions.
- AC-004: Manual and automatic compaction retain local handoff state when the server is unavailable. Resume explicitly labels stale/offline information and includes the final unuploaded tail after recovery.
- AC-005: A populated backup restores strictly into an owned isolated database; original-row hashes, counts, grants, IDs, source evidence, checkpoints and queued work match. Unknown source versions refuse preflight without writes. Any independent-store consolidation is gated by an inventory/collision report and explicit mapping.
- AC-006: Record cold/warm latency, throughput/backlog, process memory, CPU and embedding contention on a real 4-vCPU/8-GiB reference class under the recorded corpus/workload. Set justified budgets from measurements. This criterion remains open until those hardware/model measurements exist; local measurements alone do not satisfy it.
- AC-007: Provide 2–3 measured practical examples, full relevant test output, independent complete-diff review with no unresolved Critical/High/Medium defects, and link Low findings to [Issue75](https://github.com/phense/agentic-rag/issues/75).

- AC-008: A real-server40-connection repeated REST/MCP and turnover rehearsal records PSS/RSS, file descriptors, threads, database backends and disk/row growth. Queue/disk pressure rejects fresh writes while exact durable replay, reads, status and cancellation remain usable. Publish finite defaults and measured limits, including untested inference/hardware duration.

## Compatibility boundaries

Legacy local operation remains the default; no account/network dependency is introduced into existing hooks. Remote operation is explicit configuration. The service retains current embedding dimensions/model identity and all existing source evidence; legacy rows are never assigned fabricated quotes or ownership. An incompatible remote client fails before mutation. A restored old backup alone cannot recover writes accepted afterward: fence both writers and use a current target backup/forward recovery rather than claim a lossless downgrade.

## Interface contracts

| Contract | Boundary | Input | Output and invariant |
|---|---|---|---|
| IC-001 | Client/service | Protocol version, authenticated request | Capabilities or actionable incompatibility; no implicit privilege negotiation |
| IC-002 | Knowledge engine | Named tool and validated arguments | Existing JSON tool results, authorization applied before evaluation |
| IC-003 | Source ingress | Session, input/output cursors, stable evidence window | Durable receipt after commit; exact replay returns same receipt |
| IC-004 | Continuity | Session-scoped checkpoint/handoff | Owned bounded state; local fallback precedes network |
| IC-005 | Operator | Inventory/backup/restore manifest | Supported sources, integrity proof, explicit cutover/recovery limits |

## Edge cases and assumptions

Credential/config reload invalidates the next request; in-flight work remains bounded and is reauthorized before application. Empty windows must not advance a cursor ambiguously. Changed transcript prefixes require explicit recovery, not a guessed cursor. Source IDs are stable within an authenticated session namespace. Clients cannot choose a server filesystem path. Unknown project scope stays unknown and is never upgraded to global implicitly. The minimum service has static administration; dashboards, provider replacement and native plugin packaging remain #59–#73.

## Success measures

Zero changed original rows in upgrade/restore comparisons; zero duplicate applied batches after replay; zero cross-principal disclosures in the adversarial matrix; bounded responsive hooks under network failure; explicit measured limits rather than an invented SLA.

## Playbook obligations

- PB-058-01: Operator installation/enrollment/revocation and local upgrade; prove a clean and existing-local path.
- PB-058-02: Operator remote cutover, backup/restore and rollback/forward recovery; rehearse on an owned populated copy.
- PB-058-03: Agent/operator outage, spool pressure and compaction recovery; demonstrate durable local handoff and replay.

Canonical operator guide: `docs/13-central-service.md`. Public examples use synthetic data only.
