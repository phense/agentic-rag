---
id: C-060
title: Find a request and follow its job
type: task
doc_id: request-tracing
readers: [operator]
status: reviewed
version: 0.6.13
depends_on: [C-058, C-059]
assets: []
last_reviewed: 2026-10-30
summary: Find authorized operational metadata, distinguish durable acceptance from processing and recover from tracing gaps.
---

# Find a request and follow its job

Find the service call that failed or was slow, then check the current job outcome
without opening transcript or knowledge payloads. The same authorized projection
is available in **Request tracing** in the dashboard, `/v1/traces` and
`rag service traces`.

PB-060 is a system playbook for the service operator, owned by the repository
maintainer. Its origin is [Issue60](https://github.com/phense/agentic-rag/issues/60),
AC-001–007. Target: 0.6.13/schema026; last edited 2026-10-30. Review and isolated
rehearsal results belong in the [verification record](verification/issue60-tracing.md).

## Before starting

Use the current Python 3.13 service with PostgreSQL/pgvector and schema026. For a
populated025 service, take a verified backup and follow
[the service upgrade procedure](13-central-service.md#pb-058-01-install-upgrade-and-enroll)
before starting the new API. Stop writers only within an authorized maintenance
window; merging this feature does not schedule that interruption. Migration026
adds operational metadata and nullable job origins. Existing rows keep their
original knowledge, evidence and ownership. An old job may have no tracing origin.

Use an enabled human account to sign in at your configured private HTTPS origin
under `/dashboard/`. The CLI needs a client configuration with that service URL
and a protected token file; the examples use `/owned/client.toml` as an operator
chosen path. These commands read remote diagnostics and do not require client
access to PostgreSQL. Local CLI/stdio operation remains available without tracing.

## Terms used here

| Term | Meaning |
|---|---|
| Request ID | Server-generated UUID for one HTTP call, returned in `X-Rag-Request-ID` |
| Correlation ID | Valid UUID that groups related calls; it never grants access |
| Job ID | Durable source receipt or foreground-request UUID |
| Durable acceptance | The queue has committed the job; extraction may still be pending |
| Operation | Fixed service action or route template, without raw URL or query text |
| Scope envelope | Domains/projects authorized for the original call; current readers must cover them |
| Cursor | Server pagination token for the next older page |
| Capture status | Whether metadata capture is healthy, degraded or restricted to the viewer |

## PB-060: Locate a call

1. In the dashboard sidebar, select **Request tracing**.
2. Narrow the list using the known time, principal, client, operation, status,
   request ID, correlation ID or job ID.
3. Open the relevant request to inspect its duration, HTTP outcome and job link.
4. Follow the current job projection to distinguish waiting, completion, failure,
   cancellation or retry.

Expected: a matching authorized row and its current job outcome, or an empty
result. A 202 response or a durable receipt means accepted work. Only the job's
completed/applied state proves processing finished. An old origin may have
expired from tracing while its durable job remains available through the job API.

### Check through the CLI

1. List a bounded page using an enrolled client configuration:

   ```sh
   rag service --config /owned/client.toml traces --limit 25
   ```
2. Narrow that list to an enrolled client when you know its ID:

   ```sh
   rag service --config /owned/client.toml traces --client vm1 --limit 25
   ```
3. Read one request using the UUID returned in a row or response header:

   ```sh
   rag service --config /owned/client.toml traces --detail REQUEST_UUID
   ```
4. Continue a listing with the returned `next_cursor` using `--cursor`.

Expected: the same authorized metadata as the dashboard. Replace `REQUEST_UUID`
and cursor values with returned values. The service evaluates current permissions
again on every call; cached IDs do not preserve access after revocation.

### Filter or export through the API

Authenticated REST clients use `GET /v1/traces` with the usual Bearer token and
`X-Rag-Protocol: 1`. Keep credentials in the connector's private token file;
do not paste them into shell history or evidence reports. Optional filters are
`since`, `until`, `principal`, `client`, `operation`, `status`, `request_id`,
`correlation_id` and `job_id`. `limit` is 1–50, default 25; `cursor` continues an
older page. `GET /v1/traces/REQUEST_UUID` reads details.

1. Select the required scope and filters in **Request tracing**.
2. As an authorized administrator, request the bounded export or use:

   ```sh
   rag service --config /owned/client.toml traces --export --limit 25
   ```
3. Follow `next_cursor` explicitly for each additional export page.

Expected: metadata from the same authorized page, with no payloads or credentials.
`GET /v1/traces/export` is the corresponding administrator-only API. A page is
not a full archive. Preserve exported metadata in an access-controlled location;
authorization at export time cannot revoke an already downloaded file.

## Access and capture boundaries

Machine callers can inspect their own namespace; human members can inspect their
own user. Administrators can inspect other principals only where their current
read grants cover the original scope envelope. Broad original credentials may
therefore produce rows that a narrow viewer cannot see, even if the underlying
operation touched one small document. Filters only narrow this visibility.
Anonymous/global failures and deployment-wide capture counters require a human
administrator with wildcard read grants. Policy-file identity separates service
authorization realms sharing one database. Unknown and unauthorized IDs both
return not-found.

Tracing records UTC time, authenticated identity when known, fixed operation,
HTTP/semantic outcome, elapsed duration, emitted byte count, safe versions and
opaque job links. Payload capture is disabled. There is no diagnostic switch to
retain prompts, request/response bodies, full query strings, cookies, tokens or
exception text. Model inputs and stored source evidence remain governed by their
existing contracts. Operational tracing does not replace the knowledge audit.

## Retention and capacity

| Budget | Behavior |
|---|---|
| Age | At most 7 days of operational metadata |
| Rows | At most 20,000 metadata rows per deployment |
| Logical metadata size | At most 64 MiB |
| Listing/export page | 1–50 rows, default 25 |
| Origin lifetime | Durable job origin survives metadata pruning |

Tracing prunes operational metadata within finite work bounds. It never prunes
knowledge, source evidence, audit history or pending input to meet these limits.
Capture under pressure is best effort and exposes degradation; it does not
rewrite the result of an already committed audited operation. The fully scoped
administrator sees a process-local dropped count; once degraded, that recorder
keeps the warning for its remaining process lifetime. New rows can prove capture
has resumed while the earlier gap stays visible. Retained rows do not prove
complete observation during an outage. PostgreSQL file size may stay
at its reusable high-water mark after pruning; metadata limits are not a limit
on genuine knowledge growth, database backups or externally configured logs.

### Reconcile a capture gap

1. As a fully authorized administrator, inspect the listing's `capture` status
   and the service's fixed tracing diagnostic.
2. Check the existing service health, database connectivity and available storage
   without retrying a successful write merely because its trace is absent.
3. Once storage is available, run the local service-owner command to prune
   expired operational metadata:

   ```sh
   rag service --config /owned/server.toml trace-prune
   ```
4. Make a harmless authenticated capabilities call and locate its new request ID.

Expected: new metadata is visible again. Pruning is repeatable and affects only
operational metadata. If it fails, preserve the safe error code, request UUID,
UTC interval, code/schema version and capture status for the database/service
owner. Keep the gap explicit; do not infer successful job processing from an
absent trace or reconstruct missing metadata from private transcripts.

## Upgrade, interruption and rollback

A failed verified restore or migration leaves the source unchanged. Preserve its
backup and diagnostic and rerun the existing preflight after correcting the
cause. Reapplying an installed 026 migration is a no-op. Do not grant application
SQL roles access to the owner-only tracing relation to bypass an error; startup
checks reject exposed control state.

A code rollback to 0.6.12 can leave additive026 objects in place. It stops producing
new tracing without discarding knowledge/jobs created by 0.6.13. Keep the current
database and policy. Restoring an older backup after new writes would lose those
writes and is not this rollback path. Source/target deployment and interruption
still need the operator's separate authorization.

## Check that it worked

A current authorized row agrees with the response's request UUID and the job API's
current state. Another department's UUID remains unavailable. After an outage,
new rows prove capture resumed; they do not fill the historical gap. Rerun this
playbook's review and affected rehearsals when route instrumentation, permissions,
retention or queue ownership changes.
