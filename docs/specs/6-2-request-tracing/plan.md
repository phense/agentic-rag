# Implementation Plan: bounded request and job tracing

## Stable work ID

Feature `RAG-060`; specification `spec.md`; base75dc321 (0.6.12,025).

## Summary and technical context

Python3.13, PostgreSQL17/pgvector, Starlette ASGI, shared connector and existing vanilla-JS dashboard. Add owner-only bounded operational metadata in026, generated UUID/correlation context around Gateway (including Dashboard); no request body capture. Use existing principal, RLS-protected receipt/status and queue authorities rather than reconstructing permissions from caller filters. Store immutable origins alongside new accepted jobs in the same audited transaction, and retain them on replay/retry. Runtime job state is projected live.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Sequential feature | GitHub59 closed, main75dc321 includes79 | Continue60 |
| Isolation | Ignored .worktrees/request-tracing-60-20261030, feat/request-tracing-60 | Ready |
| Original data/permissions | Additive026, no canonical write bypass | 31 original tables/60 rows preserved;3 strict restores |
| Review | Entire bounded diff independent | Complete;0 open C/H/M after verified fixes |
| Version/docs |0.6.12→0.6.13 in four release files | Consistent; lock check passed |
| Production boundary | Runtime tests on owned ports55460–55462/synthetic data | No rollout |

## Implementation structure and ownership

Coordinator owns `docs/**`, `.engineering-method/**`, release metadata and final verification/report. One implementation agent owns `agentic_rag/**`, `sql/026_request_tracing.sql`, and `tests/**` for this feature. Serialize overlapping interfaces; no unrelated worker or runtime changes. Independent complete-diff review follows implementation.

## Interfaces and design decisions

IC-001: A bounded ASGI tracing wrapper records UTC start/duration/status/response size and generated IDs, never raw URL, query, headers or exceptions. Use operation allowlists/templates; unknown routes map to fixed names. Authenticated identity comes only from successful authentication in Gateway/Dashboard. Validated optional UUID correlation supports retries; never accepts caller identity. MCP semantic errors recorded explicitly, without parsing result text.

IC-002: Nullable origin UUID columns on service_windows/service_requests preserve025 rows. Context propagation through to_thread permits transactional origin writes; no foreign key to retained logs. Exact replay returns existing origin. Detail derives live status through existing authorities, including retry count and safe provider/error states; no payloads returned.

IC-003: Owner-only operational SQL relation; applications enforce viewer predicates in SQL before count/pagination/detail/export. Human own-user and machine own-namespace views; scoped administrators may inspect others only when recorded authorization envelope fits current read domains/projects. Unauthenticated/global failures require wildcard read/admin. Empty scope stays empty. Restriction is deliberately conservative for broad original credentials. Keyset cursor anchored to server time/UUID; inputs strictly bounded and parameterized; filters narrow only. Export is explicit admin-only with identical scope/page ceiling.

## Storage/failure decisions

Seven-day/20000-row/64MiB logical metadata budget, fixed per-row fields; serialize admission/pruning and stop recording on finite capacity. Never delete canonical state or unacknowledged input. Background/repeated prune bounded; no timer per connection. Bounded logger concurrency plus PostgreSQL connection/lock/statement timeouts, no unbounded task spawn. Fixed, throttled process diagnostic and in-memory saturating counters expose degraded capture. Logging best effort never overrides an already committed HTTP/job outcome; trace API fails visibly503 on storage failure. Payload capture disabled, no diagnostic raw-capture switch in this release.

## Tests and compatibility

Test-first metadata/redaction, current scope and export checks, receipt/replay origin, foreground outcomes, retry/provider refusal, failed logger and HTTP outcome, keyset churn, retention/capacity/locks, CLI/REST/dashboard equivalence. Browser E2E exercises real form/navigation/details. Full suite serial on owned isolated cluster55460; no production DB/model use. Rehearse populated025 backup/strict restore/additive026/retry and original hashes/ACLs; old clients ignore additive headers. Rollback code only; retain026 columns/table and new knowledge. No down migration or old-backup restore after new writes.

## Architecture findings

See `docs/uml/findings.md`, AF-060-01..03: scope envelope, durable original link, bounded logging failure. All are task prerequisites. One sequence diagram explains the cross-component durable-origin/failure boundary.

## Dependencies

Merged58/59/68 service APIs and queue; no third-party tracing backend/provider. Initial default5432 test attempt failed authentication; owned55460 is the actual test target. Native thread worktree tool is bound to the unrelated sysadmin project; guarded ignored repository worktree fallback used.

## Playbooks

PB-060 system operator deliverable extends `docs/16-request-tracing.md` with retention, access, upgrade/rollback and outage recovery. Coordinator authors/reviews after actual commands exist. Existing verified-upgrade procedure reused for disposable025→026 rehearsal; no new production operation.
