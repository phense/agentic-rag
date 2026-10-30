# Feature Specification: bounded request and job tracing

## Stable work ID

- Feature ID: `RAG-060` (roadmap6.2, GitHub #60)
- Artifact path: `docs/specs/6-2-request-tracing/spec.md`
- Status: Accepted for implementation under the end-to-end roadmap request
- Source request: Explain failed/slow agent calls through authenticated operational metadata without exposing knowledge, credentials or transcripts.

## User scenarios

### US-001: Follow a request to its current job outcome (P1)

An operator finds a request by time, client, principal, operation, outcome or correlation/job ID, opens it, and distinguishes HTTP completion, durable acceptance, pending/running processing, success, cancellation, retry and provider refusal. Test with real HTTP and queue components using synthetic data.

### US-002: Read authorized diagnostics through interchangeable clients (P1)

A signed-in human uses the dashboard; an authenticated API/CLI caller gets the same server-side bounded projection and current access checks. An operator with restricted knowledge permissions cannot discover other departments through rows, totals, details or exports. Disabled/revoked clients lose access on the next call.

### US-003: Operate within finite budgets and recover from telemetry outage (P1)

Repeated calls do not retain unbounded state. Expired metadata is pruned without changing canonical knowledge, jobs or audit. Logger failure cannot undo an audited mutation, replay a write or turn an HTTP error into success; the operator gets a fixed minimal diagnostic and visible degraded tracing status.

## Acceptance criteria

- AC-001: Every handled service HTTP request gets a server-generated UUID and response header, UTC start time, operation template, HTTP status/error class, duration, actual emitted response bytes, safe server/client version and authenticated user/client identity when known. Caller-provided values never establish identity. Unauthenticated diagnostics have no caller-asserted identity and are restricted to fully authorized operators.
- AC-002: Accepted source and foreground jobs retain originating request/correlation identity transactionally; exact replay preserves original origin while linking later retry/status calls. Detail uses existing current-authority job projections, never captured payloads. HTTP202/durable enqueue is explicitly distinct from applied/completed processing.
- AC-003: Dashboard, REST and CLI support equivalent keyset pagination and time/principal/client/operation/status/request/correlation/job filters. Concurrent new writes do not duplicate or displace older pages. A bounded JSON export uses the same scope and pagination contract.
- AC-004: No request/response payloads, raw URL/query strings, authorization/cookies, passwords, exception strings, prompts or transcript excerpts enter tracing, including failure paths. Payload capture remains disabled; diagnostic expansion would require a future explicit reviewed contract.
- AC-005: Rows, details, totals and exports enforce current read authority. No arbitrary SQL grants on the operational table. Unknown and unauthorized request/job IDs have indistinguishable not-found behavior. Restricted administrators do not receive global failures/counts.
- AC-006: Retain at most7 days/20000 rows/64MiB logical metadata per deployment, finite per-row fields, bounded concurrency and timeouts. Saturation preserves canonical state and reports fixed degraded telemetry rather than silently pretending complete logging. Provide a finite pruning operation that changes operational rows only.
- AC-007: Rehearse populated025→026 migration, repeated migration/restore, unchanged original rows, existing REST/MCP/queued client behavior, deliberately secret-shaped fixtures, logger outage/lock pressure, and request-overhead/storage measurements under concurrency. Complete bounded diff independently reviewed; no Critical/High/Medium findings remain.

## Functional requirements

FR-001: Metadata-only operational traces are separate from immutable audited knowledge mutations.
FR-002: Current server-derived permissions govern every tracing view. Conservative scope-envelope filtering is permitted; undocumented metadata leakage is not.
FR-003: Original accepted-job identity survives HTTP disconnection/retry, worker restart and trace retention expiration. Job state remains owned by its existing queue, not a duplicate trace state machine.
FR-004: Local CLI/stdio remains supported without a service; tracing is a service capability and never starts inference or creates a second canonical store.

## Compatibility boundaries

Preserve0.6.12/schema025 originals, grants, evidence, IDs and queued work. Add026 atomically through the existing verified operator upgrade; never migrate at API startup. Existing clients can ignore new response headers and optional response fields. Version bump exactly0.6.13. Old code can run against additive026; downgrading code hides tracing without discarding new writes. Merge does not authorize rollout.

## Interface contracts

| ID | Boundary | Inputs | Outputs | Invariants |
|---|---|---|---|---|
| IC-001 | Transport→trace | Server request UUID, optional validated UUID correlation | Safe metadata and response header | No raw paths/arguments/errors |
| IC-002 | Trace→queue | Origin request/correlation IDs | Owned receipt/request identity and current outcome | Durable origin in original transaction |
| IC-003 | Viewer→projection | Bounded filters/keyset cursor | Rows, scoped count, next cursor/detail/export | Current authority on every call |

## Edge cases

Lost response after accepted write; duplicate idempotency key; rejected upload; unsupported protocol; invalid credentials; non-HTTP/lifespan; MCP semantic failure under HTTP200; revoked/changed scopes; unauthenticated unknown path containing secrets; stale cursor; log-store lock/outage; expired origin trace with retained job; retries accepted under fresh authority; connection churn.

## Assumptions and unresolved decisions

GitHub remains canonical. #59 is merged, #68 implementation is already merged via77 but its separate live acceptance remains open. Roadmap order continues60→61 etc.; no feature is counted complete merely from a merge without required evidence. No external provider or private-corpus calls are needed for tracing acceptance. The maintainer confirmed #75 as the rolling Low findings issue; #74 is an already merged PR.

## Success measures

SC-001: Two synthetic departments cannot see one another in any diagnostics projection.
SC-002: Acceptance report includes2–3 before/after examples with sample counts, measured overhead/growth, exact revisions and commands, and stated host/duration limits.
SC-003: Existing affected/full suites and independent review have actual successful exits before PR delivery.

## Playbook obligations

PB-060 (operator, source AC-006/007): extend existing service upgrade/recovery instructions with tracing retention, failure diagnosis, permissions and export; demonstrate isolated upgrade and outage recovery. Documentation is a delivery prerequisite.
