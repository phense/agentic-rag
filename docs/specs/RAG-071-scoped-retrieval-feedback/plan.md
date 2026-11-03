# Implementation Plan: Scoped retrieval feedback

## Stable work ID

- RAG-071, specification `spec.md`; source0.6.27/schema036, target0.6.28/schema037.
- Status: approved within autonomous execution; architecture gate precedes tasks.

## Summary

Use explicit write tools for feedback-enabled search and feedback mutation.
Ordinary `memory_search` and read-only MCP remain untouched. One audited gateway
owns immutable retrieval-event metadata and versioned usefulness signals, with
the existing scoped writer connection and commit-authority checks. Approval and
cross-user aggregation are local operator operations. Extend the existing private
confirmed-failure evaluation entrypoint with a distinct approved-feedback format;
never reinterpret feedback as factual corrections.

## Project gates

| Gate | Evidence | Response |
|---|---|---|
| Canonical acceptance | Issue71, read2026-11-03; spec AC-001..009 | No automatic truth/ranking mutation |
| Audited writes | AGENTS.md; evidence/store gateways | Separate audited metadata gateway; no ad hoc knowledge writes |
| Existing installation | Both production hosts0.6.27/schema036 | Additive037; populated archived027 upgrade/restore |
| Security/review | Existing request_scope, RLS, ServiceConnection commit checks | Reuse these; independent complete-diff review |
| Release | Main0.6.27 | Exactly0.6.28, lock/README/changelog/supported labels |
| Test cost | Maintainer requested sparse full suites | Targeted red/green per slice; one final full run before PR |
| Privacy | Metadata-only tracing026; private correction files | No raw query in capture; local approved private query only |

## Technical context

Python3.13, psycopg3, PostgreSQL17+pgvector. Reuse `db.connect`, `service.context`,
`store` audit convention, `evidence_contract.document_version`, `search.search`,
`mcp_server` registration, `service.engine` dispatcher and `client.RemoteClient`.
Service REST already exposes every registered tool at `/v1/tools/{name}` with
authentication, limits and queued-tool compatibility. Reuse that surface rather
than adding a competing protocol. CLI lives in a small `feedback_cli.py` module.

`service_requests` retains results only300seconds and tracing026 deliberately
retains no content. Neither is a durable feedback snapshot. Migration037 adds
separate event/signal/approval tables, not columns that change existing tables.
`benchmark/corrections.py` already seals private files outside Git and separates
source families; reuse its privacy/path helpers without weakening its original
correction validator.

## Compatibility boundaries

Default `[feedback].enabled=false`; no additional work in existing search paths,
no provider calls, backfill, recoding or rank changes. A dedicated
`memory_feedback_search` requires an explicit domain and exact project or global
scope, an idempotency key and bounded options. It calls the ordinary search engine
and returns its ordinary results plus event metadata. Search failures/capture
failures are explicit; no fabricated event is returned. Existing source and
embedding models are not changed. The feature must work without an embedding
provider using explicit lexical search.

Migration037 changes no001..036 file. Existing0.6.27 readers ignore the new tables;
their operator inventory may reject a newer schema. Rollback disables feedback
and reuses027 code while retaining037 data; never drop tables to roll back code.
Upgrade source/target backups require independently restored row/ACL/owner checks.

## Data and ownership

- `retrieval_feedback_events`: immutable UUID event, namespace, actor/client,
  domain/project, query SHA256, canonical request/settings digest, bounded
  metadata snapshot of result IDs and document/source versions, runtime and
  non-secret model/config hashes, optional origin request/correlation IDs.
  Never store raw query, titles, bodies or snippets. Same namespace/key and same
  input digest returns the original event; conflicting reuse is409.
- `retrieval_feedback`: one UUID signal, event reference, immutable owner and
  independence identity, kind, selected/expected IDs and versions, redacted
  comment, active/retracted state, optimistic revision and bounded JSON history.
  Snapshot fields are immutable; update permitted only to signal fields. Each
  update/retract appends history and an audit in the same transaction.
- `retrieval_feedback_approvals`: operator-only local table, signal/revision,
  exact safe reconstructed query, expected eligible document/version, family
  identities and approval timestamp. No grants to reader/writer/admin roles.
  Approval is current only while signal revision/state and all cited versions
  match. Mutating a signal invalidates approval by revision mismatch, without
  granting writers access to the private query.

For scoped connections, event/signal RLS requires both the current namespace and
the existing domain/project visibility/write helpers. Their namespace and actor
are derived from CURRENT. Local CLI derives identity from the OS, with no
caller-supplied impersonation argument. Local DB owners retain existing trust.
Reader gets SELECT only; writer gets event INSERT, signal INSERT/limited UPDATE.
Use immutable-identity triggers and validate the expected ACL/RLS shape at
service startup. No new SECURITY DEFINER or LEAKPROOF helper is needed.

Use a namespace transaction lock for idempotency, rate and quota checks. Initial
limits: event<=64KiB, k<=20, <=20result IDs, <=16source versions/result; signal
comment<=1000characters; <=32revisions; <=1024events and2048signals per namespace,
<=16MiB logical metadata per namespace, <=120new events/signals/updates per hour.
Fail closed at caps; no silent TTL removal of acknowledged feedback. Operator
pruning, if offered, is explicit and keeps approved/referenced records intact.
The existing aggregate service budget and rate limits apply unchanged.

## Interface contracts

| ID | Producer/consumer | Change | Failure |
|---|---|---|---|
| IC-001 | `memory_feedback_search` / CLI `feedback search` | Explicit bounded search plus event | Disabled, unavailable, cap, key conflict |
| IC-002 | `memory_feedback_submit/update/retract` | Typed writer operations; strict revision | Uniform unavailable for foreign/missing; conflict409 |
| IC-003 | `memory_feedback_get/list` | Own authorized metadata only | Recheck live visibility; no private query |
| IC-004 | Local CLI `feedback approve/summary/export` | Operator-only; reject request/fence/read-only contexts | Unsafe query, stale evidence, private-path refusal |
| IC-005 | Existing corrections evaluation entrypoint | Dispatch separate `private-retrieval-feedback` format | Reject mixed formats, tampering and family leakage |

Export at most32approved negative cases to a0600file in a0700directory outside
Git. Reconstruct a query of at most512characters; require hash match with the
event and reject secret-shaped or redacted text. Select one currently eligible
expected document; validate domain/project and all versions. Source keys/spans
form connected families across cases; use deterministic whole-family dev/test
assignment, ignoring vote counts. Export no comments, credentials or full result
bodies. Offline evaluation is read-only and network-free lexical retrieval;
report baseline miss, current hit/miss, stale/withheld and per-split denominators.
Do not select/tune a candidate using held-out results or activate a new profile.

## Dependencies and implementation structure

One writer owns runtime, SQL and tests. `agentic_rag/feedback.py` owns the metadata
gateway; `feedback_cli.py`, MCP registration and existing REST dispatcher are
adapters. `benchmark/feedback.py` owns private evaluation, with a narrow dispatch
from `benchmark/corrections.py`. Schema validation, backup/upgrade inventories,
configuration and release labels are updated together. Parent coordinator owns
spec/plan/tasks/UML, continuity and final acceptance; no overlapping writers.

## Tests

- Targeted core: new `tests/test_retrieval_feedback.py`; real isolated PostgreSQL,
  synthetic source-backed claims and stub embeddings, no provider. Red before code.
- Privacy/authorization: service principals with two users and two machines,
  read-only denial, live revocation, foreign IDs, strict versions, same-key races,
  forced audit failure and unchanged knowledge-table hashes.
- Contracts: real REST dispatcher and MCP registration, RemoteClient/CLI; three
  executable workflows including retraction and private failure evaluation.
- Evaluation: sealed file/hash/path checks, connected-source split integrity,
  stale/withdrawn/changed evidence, no provider or writes; old format unchanged.
- Upgrade: populate archived027 with domains/projects/claims/pin/vector/queued
  work; atomic interruption/retry, source/target dump-restores, old reader and
  disabled-feature rollback. Include owner/ACL preservation.
- Final: affected regression selection, lock/wheel/Node as relevant; one full
  suite on final runtime before PR, independent complete bounded diff review.

## Architecture findings

Design questions and dispositions are in `docs/uml/retrieval-feedback-71.md`
and AF071-001..006 in `docs/uml/findings.md`, before task generation. No general
cache, connection pool, provider, ranking loop or global telemetry subsystem is
introduced.

## Supporting artifacts

No separate research/model/contract tree is required: the uncertainty is data
ownership and privacy, resolved by the model and contracts above. The existing
private evaluation format is preserved; feedback uses a separate format.

## Playbook obligations

PB07101, system deliverable, `docs/retrieval-feedback.md`: writers/operators,
AC-003/005/007/008/009. Review and execute before first enablement. Include exact
commands, dry-run/preview where useful, failure paths, preserved data, private
exports, source withdrawal and rollback with retained037. Development upgrade
rehearsal uses the same canonical procedure on an owned populated source; no
separate development playbook is needed. Content review alone is not execution.
