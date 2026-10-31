# Source evidence contract v1 (as built)

Implementation: `agentic_rag/evidence_contract.py` (read producer, versions,
errors), `agentic_rag/evidence.py` (`review`, `source_state` with optional
strict mode), `sql/029_source_evidence.sql` (revisions, history, triggers).
Names below are final and shared by local/central CLI, MCP, REST and dashboard.

## Operations

| Surface | Read | History | Strict claim review | Strict source trust |
|---|---|---|---|---|
| MCP (both levels for reads; RW for writes), REST `POST /v1/tools/<name>` | `memory_evidence(id_or_slug, source_key=None, cursor=None, limit=20)` | `memory_evidence_history(id_or_slug, source_key=None, cursor=None, limit=20)` | `memory_review_claim(id_or_slug, state, reason, expected_version)` | `memory_source_state(source_key, state, reason, expected_version, id_or_slug)` |
| CLI (local SQL or, in client mode, the service) | `rag evidence show ID [--source K] [--cursor C] [--limit N] [--json]` | `rag evidence history ID [...]` | `rag evidence review ID --state S --reason R --expected-version V` | `rag evidence source-state K --state S --reason R --document ID --expected-version V` |
| Dashboard `/dashboard/api/tools` (queued) | `memory_evidence` | `memory_evidence_history` | `memory_review_claim` (version required) | `memory_source_state` (version and anchor required) |

Legacy calls without `expected_version` remain valid outside the dashboard.
The dashboard rejects them with `400 expected_version_required` for writers;
read-only principals still receive the existing `403`.

## Envelope (`memory_evidence`)

```text
contract_version: 1
document: {id, slug, title, domain, project_scope}
version: "ev1:<64 hex>"
claim: null | {kind, review_state, review_reason, review_reason_truncated, revision, support_basis}
lifecycle: {document_status, fact: null | {state, disposition, relation, event_at, expires_at}}
eligibility: {current, claim_eligible, reasons[], notices[]}
provenance: {registry: claim|legacy_unmanaged, status: complete|incomplete, independent_user_events}
verification: {independent: false, origin: none|operator_review}
sources: {items[], total, distinct_sources, limit, truncated, next_cursor}
```

Source item: `source_key`, `span_hash`, `reference` (`<source_key>#<span_hash>`),
`source_version` (`src1:<64 hex>`), `revision`, exact `quote` (≤4000 chars,
`quote_truncated`), `completeness` (`complete|partial`), `reviewed`, `role`,
`origin` (`user_source_event|assistant_statement|manual_attestation|unknown_role`),
`source_event_at` (ISO or null), `event_time` (`known|unknown`),
`trust` `{state, reason, reason_truncated, changed_at}`. No namespace, source event ID, transcript
path or URI is returned.

- `support_basis`: `operator_review`, `complete_user_statement`, `manual_attestation`, `none` or
  `legacy_unmanaged`. Manual attestations retain canonical eligibility but never
  count as independent user events. The counter counts distinct active user
  source events, including partial ones, excluding local `operator`/`manual`
  namespaces and service `svc1:…:manual:…` namespaces. Repeated spans count once.
- `fact.state`: `current|future|expired|superseded|not_accepted|no_event_time`.
- `reasons` (exclusion, empty when current): `document_archived|document_refuted`,
  `claim_refuted`, `review_required`, `no_active_support`, `fact_<state>`, `not_current`.
- `notices`: `legacy_provenance_unknown`, `source_withdrawn`, `partial_quote`.
- `current` = `documents.status='active' AND assertion_eligible(id)`; reasons
  explain the canonical predicates and never override them.

Paging: `limit` 1–20 (strict int), keyset cursor `<source_key>.<span_hash>`,
at most 64 KiB of JSON-encoded quote bytes per page (history: 64 KiB of encoded reasons) (`truncated=true` when the byte budget
ended the page). Source items also share an 80 KiB encoded-item budget, including trust reasons and metadata. Source trust and claim review reasons are bounded to 1000 characters with explicit truncation flags; original stored reasons remain unchanged. Totals count only the anchored document's spans.

## History (`memory_evidence_history`)

`{contract_version, scope: claim|source, anchor, items[], limit, next_cursor,
pre_upgrade_history: "not_captured"}`. Items, newest first by revision:
`revision, operation (attach|review|span_review|source_state), state, reason
(≤2000 chars, reason_truncated), actor, concurrency (strict|legacy|direct),
inspected_version, recorded_at` plus `source_key/span_hash` for claim events.
Cursor is the last revision returned. Source history never includes document IDs.

## Versions

- `ev1` = SHA-256 over: document id, domain, project scope, status, refuted_at;
  claim kind, review state, content hash, claim revision; every span (source key,
  span hash, quote SHA-256, complete, reviewed) with its source's state, role,
  event time and revision; the fact's disposition, event/expiry time and relation.
- `src1` = SHA-256 over source key, revision, state, role, event time.
- Timestamps enter as epoch numbers; no xmin/ctid; stable after dump/restore.
- Revisions: `source_revisions`/`claim_revisions`, absent row = baseline 1
  (storage-contract baseline, not a historical claim). Triggers increment them
  on every source update, claim update and span insert/update; values never repeat.
- Supersession by another memory, expiry relative to now and scope are evaluated
  live at read time and are not frozen into `ev1`.

## Decisions and errors

- Strict review: lock the writable document row `FOR SHARE`, then `claim_records`,
  then per-source advisory locks and source row `FOR SHARE` locks in key order
  (≤128 sources, else `evidence_too_large`), recompute `ev1`, compare,
  update flags/claim, history and audit in one transaction. Returns
  `{document_id, review_state, version, revision}`.
- `rag_lock_claim_source(uuid,text)` returns no source data. It uses a fixed
  definer search path and explicitly checks readable and writable anchor scope
  plus source membership before taking a shared row lock. This permits reviewing
  a readable shared source without granting source-wide mutation. Reader/PUBLIC
  execution is denied; service schema checks validate the helper and its grants.
  Row locks serialize even pre-029 writers that take no advisory lock.
- Strict source trust: per-source advisory lock, anchor must be readable and
  linked, `SELECT … FOR UPDATE` applies the service all-dependent write policy,
  compare `src1`, update, history and audit. Never locks claims. Returns
  `{source_key, state, source_version, revision, version}`.
- `evidence_conflict` (HTTP 409): version changed; nothing written.
- `evidence_unavailable` (HTTP 404): missing, inaccessible, unlinked, or (strict
  source) a shared source with an unwritable dependent. Same body for all.
- `invalid_arguments`/ValueError: malformed version, cursor, limit, or reason
  longer than 1000 characters in strict mode.
- Service commit authority is rechecked at commit (`authorization_changed`, 403).
- Legacy calls also advance revisions and append `legacy` history without an
  inspected version; changes outside the gateway are recorded as `direct`.
