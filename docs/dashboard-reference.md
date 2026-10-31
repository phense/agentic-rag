---
id: R-059
title: Dashboard boundaries and limits
type: reference
doc_id: dashboard-reference
readers: [operator, knowledge-user]
status: reviewed
version: 0.6.15
depends_on: [C-059]
assets: []
last_reviewed: 2026-10-30
summary: Access authority, setup checks, browser security and finite resource budgets.
---

# Dashboard boundaries and limits

The dashboard uses the same PostgreSQL store, scoped service engine and bounded
foreground queue as agent plugins. It is available at `/dashboard/` when the API
runs. Standalone CLI/stdio users can keep working locally without it.

| View | Available to | Contents |
|---|---|---|
| Overview | Signed-in humans | Scoped memory/domain/pending-review counts and recent previews |
| Knowledge | Signed-in humans | Scoped browsing/search, originals, assertions, provenance and review state; evidence contract v1 drilldown with source/claim history and version-bound review and source-trust actions ([claim evidence](claim-evidence.md)) |
| Clients & access | Human administrators | Configured people/VMs, safe credential IDs, effective permissions, queue/provider state and administrative changes |
| Settings | Human administrators | Server-wide reranker preset, language support, local availability and audited preview/apply |
| Setup assistant | Human administrators | Four explicit installation paths, saved checks and read-only configuration plan |

## Access and configuration

The protected policy file defines users, machines, scopes, enabled state, key
verifiers and password verifiers. It takes precedence immediately on the next
request. There is no second database-backed permission engine. A human admin
can administer configuration while seeing only their own permitted knowledge.
Machine scopes narrow their owner's rights. Shared history teams preserve
separate uploader cursors, credential ownership and mutations.

Dashboard administration uses a validated preview/apply flow with an exact
revision. Applying a stale preview returns 409. Generated secrets are returned
once and never retained in administrative audit. Rotation of an existing key ID
invalidates its old revision. Revoke removes that ID. A disabled machine or a
machine with no active key cannot authenticate. **Stale** means no observed
authenticated activity in five minutes; it does not revoke access.

The reranker preset is editable through **Settings**, using the same protected
policy file and administrative journal. Other runtime and model configuration
remains file-owned and read-only. See [the selection and upgrade procedure](reranker-settings.md).
The setup export is a credential-free template and operator instruction plan.
The browser does not run DDL, reinitialize a database, merge stores, move data or
restart services. Follow [the operations guide](15-dashboard.md) for prerequisites.

## Saved setup checks

| Check | What verified means | Cost and failure boundary |
|---|---|---|
| Database & schema | Current migration and scope protections present | Metadata checks; fail closed on unsafe roles/policies |
| Required permissions | Live admin and required scoped roles validate | No privilege escalation |
| Embedding access | Known model digest and actual matching-dimension synthetic embedding | One 10-second embedding call; yields to foreground |
| Provider access | Actual synthetic structured response from the configured service account | 20 seconds per process; Codex login preflight plus call can take up to40 seconds; no stored knowledge input |
| Client / server compatibility | Authenticated discovery of the operator-configured `service.url` using its protected `service.token_file`; actual protocol1/queued_tools1 response |2-second HTTP bound, no outbox; missing target/credential remains incomplete |

Saved check results include time and a configuration fingerprint. Changed policy
or configured runtime/model identifiers, compatibility URL or token bytes mark them stale. The saved compatibility result binds an opaque target ID, protocol and reported server version; changing a remote server requires rerunning discovery. The embedding check
validates the actual digest at probe time; a silent replacement behind the same
configured name requires rerunning that check. Completion requires every current
check to be verified and can be repeated. A successful check is a point-in-time
observation, not continuous provider availability monitoring.

Pending-only filtering applies to the paginated browse list. Entering a text query explicitly clears and disables that selection; clearing the query makes it available again. Text search does not claim to filter a capped result page by review state.

## Browser security

HTTPS sessions use a host-only HttpOnly/Secure/SameSiteStrict cookie lasting up
to eight hours. Unsafe browser actions also require the original Origin and a
session-derived CSRF token, which protects against another site submitting a
request under your cookie. Password login is rate-limited. Logout, expiry,
password rotation or account disabling invalidates subsequent requests. External editors must honor the policy sidecar file lock or pause dashboard writes. Policy apply locks the exact session row through the atomic file replacement: completed logout blocks a later commit; concurrent logout waits for an already authorized commit. Expiry is checked again immediately before replacement.

The existing REST/MCP interfaces still require Bearer credentials; dashboard
cookies cannot authenticate them. Machine keys cannot open a dashboard session.
Responses are no-store, scripts/styles are packaged locally, framing is denied,
and credentials are not written to browser persistent storage. Loopback HTTP
uses a separate cookie and is intended for private local access/testing.

## Resource budgets

| Resource | Limit / behavior |
|---|---|
| Dashboard API concurrency | 4 active requests, separate from legacy/control admission |
| Browser body |64 KiB received within 5 seconds |
| Login/bootstrap attempts | 5 per minute per actual peer,1024 bounded buckets |
| Human sessions | 16 per user,10000 total; expired records swept at login |
| Knowledge page | 25 default,50 maximum; SQL bounds previews before transfer |
| Dashboard response |512 KiB; queued tool results retain the existing120 KiB limit |
| Setup model checks |1 globally; foreground work defers them with 429 |
| Reranker selection checks | Fixed synthetic query, total1500ms per check; shared native runtime rejects concurrent inference |
| Policy-managed principals | 256 people and256 machines;8 active keys per machine |
| Administrative journal | 10000 rows; reaching capacity refuses further changes instead of evicting audit |
| Freshness observations |Configured IDs only,60-second write throttle,1,024 process cache entries |

Background transcript extraction remains a single fenced worker. A browser or
agent session does not allocate its own model runtime or permanent database
connection. These budgets bound admission and retained records; they are not a
latency guarantee. The [verification record](verification/issue59-dashboard.md)
states the measured host, workload, memory/disk observations and limits.

## Stable errors and recovery

| Status / code | Meaning / next action |
|---|---|
|401 invalid_credentials | Sign in again; if repeated, ask the file owner about current access |
|403 origin_denied/csrf_denied | Use the original dashboard address and reload the page |
|403 administrator_required/scope_denied | Request the specific rights needed; no automatic broadening |
|409 policy_revision_conflict | Reload and preview against the current authoritative file |
|400 expected_version_required | The dashboard sends review and source-trust changes only with the inspected evidence version; reload the memory |
|evidence conflict (failed queued request) | The evidence changed after inspection and nothing was saved; select **Reload evidence** and decide again |
|409 last_administrator_required | Keep a valid enabled human administrator |
|409 setup_checks_incomplete | Run missing/stale checks before completion |
|429 capacity/busy | Agent work has priority or a bounded control is busy; retry explicitly |
|507 storage/audit budget | Operator must resolve storage or audit archival before new changes |
|503 policy_recovery_required | Preserve current policy and prepared audit; file/database owner reconciles known digests |

The0.6.13 [request tracing view](16-request-tracing.md) adds scoped metadata and
current job diagnostics under finite retention. This0.6.12 dashboard reference
describes its original administration surface. Advanced model replacement remains
roadmap6.3. Tracing never captures raw prompts or session payloads.
