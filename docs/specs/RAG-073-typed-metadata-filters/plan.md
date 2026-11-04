# Implementation Plan: Typed metadata filters

## Stable work ID

- Feature ID: `RAG-073`; [canonical73/6.15](https://github.com/phense/agentic-rag/issues/73).
- Specification: `docs/specs/RAG-073-typed-metadata-filters/spec.md`.
- Artifact path: `docs/specs/RAG-073-typed-metadata-filters/plan.md`.
- BASE: `a151ee5918cf4b1d8e0e8b18bddfe4adadc7658b`, deployed029/schema038.
- Status: Runtime039 and root exact-set/adapter rehearsal complete; as-built
  reconciled. Independent PB review, final checks and both production updates pending.

## Summary

Use a single typed, bounded AST and an optional32-field operator registry for
namespaced application metadata. Fixed canonical selectors are read-only. New
optional query arguments enter existing local/central entry points. Explicit
predicates narrow each candidate query before its own LIMIT. Existing authority,
source/truth/temporal/lifecycle helpers remain untouched; optional filters must
never change which newer assertion supersedes an older one.

Additive039 supplies pure invoker matching helpers and separate filtered SQL
retrieval/graph functions where needed; old signatures and unfiltered functions
remain intact. Direct Python SQL readers use the same matcher. No RLS policy,
privilege, provider, daemon or cross-request cache changes. Filtered derived views
revalidate matching originals through an uncached bounded path instead of reusing
unfiltered aggregate text. Metadata writes use save_document, not a side channel.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Canonical sequential work |72 closed after verified029 on both hosts;73 OPEN | pass |
| Existing source/evidence boundary |store.py, service/context.py, queued_transaction.py, fence.py | preserve; explicit predicates only |
| One patch and relevant docs |pyproject/uv.lock/README/CHANGELOG;029→030 | implementation task |
| Published migrations immutable |001..038 on BASE |039 only; fresh byte checks |
| Existing-install compatibility |three populated stores, old scoped clients and jobs | archived029 fixture/retry/restores required |
| Independent risky review |AGENTS.md complete bounded review | final required; small mechanical corrections root |
| Autonomy |latest user directs automatic numbered delivery/important choices only | routine PR/merge/deploy authorized |
| Test cost |user fullsuite sparingly nearPR | focused selections while changing; one full at delivery |

## Technical context and inventory

Python>=3.13, psycopg3/PostgreSQL17/pgvector;155 runtime modules and38 migrations.
`documents.meta` is existing arbitrary JSONB; `store.save_document` strips secrets,
merges metadata and preserves scope and audited canonical rows. Existing internal
keys include project applicability hints; provenance and canonical columns are
separate. CLI/MCP save currently does not expose arbitrary metadata. Do not
reinterpret historical metadata or treat an application label as verification.

Affected readers are `search.py` (raw/contextual/planned and managed generations,
identity shortcut and graph expansion), `indexes.py`, `vector_plan.py`,
`graph.py`, `research.py`/`research_worker.py`/`research_exploration.py`,
`entities.py` where research provenance expands, `context.py`, `profiles.py`,
`thematic.py`, and document-backed pins/checkpoints in `hooks/session_start.py`.
`domains.list_domains` counts and `benchmark/corrections.py` private original
export need explicit consistent opt-in filters. Export labels/expected sources
must still be eligible; no filter can change the benchmark ground truth silently.
Library, CLI, MCP, service engine/admission/OpenAPI and client negotiation must
share the contract. Bound research worker messages explicitly include the filter.

Local tests use PG55460 only when no other run owns it, or a dedicated owned
socket cluster. Only synthetic/authorized read-only measurement data; no private
production content or external model call. Retain old failed evidence separately.

## Typed registry and data model

Introduce `metadata.py` for registry validation, strict JSON decoding,
AST normalization, type/operator matrix, value-free errors and a small independent
reference evaluator used only by tests. Runtime SQL must not be generated from
arbitrary identifiers, SQL text or JSONPath.

Proposed TOML: `[metadata.fields]` maps simple names to fixed type strings. At
most32 application keys; default empty. Fixed builtins are reported separately.
Expose an authenticated `memory_filter_schema` read tool and library equivalent
with registry version/operator matrix/limits. Inspect never enumerates values.
New `metadata` save argument stores only `meta.application={version:1,values:{...}}`;
all sibling existing meta keys survive. Validations run only when supplied.
Reject an occupied incompatible legacy application envelope rather than overwrite
it. Registry removal/change must not rewrite rows: old unmatched types are
reported as nonmatching, operator changes require validation and a rehearsal.

Canonical field resolver reads fixed dtype/status/slug/timestamps and joins
claim_records for review_state. User filters cannot name domain/project/user/
machine/role/source privilege fields. Explicit existing selectors remain mandatory.
New metadata never enters evidence fingerprints as a new claim of truth; normal
save/version/audit behavior stays authoritative.

## Candidate and result integration

`sql/039_metadata_filters.sql` defines bounded pure invoker matching from supplied
JSONB/known scalar columns and normalized AST. Functions retain no caller authority,
no SET placeholders, no SECURITY DEFINER and no LEAKPROOF. Defensive input limits
remain enforced for direct invoker calls. Matchers use CASE before typed casts;
malformed legacy data is nonmatching, not a whole-query cast failure. Calendar
and timestamp parsing must be independent of caller timezone/DateStyle.

Create explicitly named filtered siblings of the039-needed baseline functions,
copying the actual038/034/020 definitions and adding a match predicate at each
original-document boundary before vector/lexical/group/pool limits. Unfiltered
calls keep the original function and old result shape. Do not append WHERE to an
already-limited baseline result. Parameters, not interpolated paths or values.

For ANN, gate both the continuation and exact fallback on the full authorized,
mandatory-eligible and metadata-matching set. Filtered exact fallback may scan a
bounded visible scope; reject over-budget work explicitly. Managed-generation
and contextual source-hash/model gates remain before candidate limits. Test more
than256 hidden nearer chunks and more than256 permitted farther documents, not
only the small exact path. Generic prepared plans/current revocation stay covered.

Graph paths require every node and both endpoints to match; a nonmatching bridge
cannot reveal hidden labels or create a path. Research search/entity/graph/dependency
expansion must carry the filter through every hop before their limits. Optional
selection never alters trust checks on a source or superseding dependency.

Filtered context returns only eligible matching document-backed context; exclude
anonymous pins and unbound session/checkpoint text with an explicit warning.
Do not reuse a theme/profile/pattern aggregate that contains nonmatching source
material. Build a bounded source-only filtered view or declare unavailable; a
successful empty aggregate must not silently stand in for exhausted work.
Filtered count/export apply matches and mandatory gates before counting/limits.
Export failure publishes no partial output file. No filter means unchanged old
behavior, including existing pin/checkpoint/cache semantics.

## Bounds, plans and indexes

AST limits are FR-006. Add a bounded read scope that preserves a caller's shorter
statement/lock timeout and restores it on success, errors and autocommit. Keep
all existing request/engine/model budgets. Initial maximum examined document set
50,000 and explicit `filter_budget` above it; choose a limit+1 probe, not an
unbounded eligibility count. This exceeds the current representative stores and
is a declared capacity bound, not silent truncation.

Measure equality/list/range/string plans on a synthetic representative store.
At most one shared JSONB application-value GIN index and justified fixed-column
indexes; never create an index per user key. Indexes may aid selected plans, but
do not claim GIN-before-RLS behavior. If measured plans do not benefit, omit an
index and publish the bounded scan/deadline instead. No session pooling or security
boundary change is in scope. Avoid one recursive matcher invocation per chunk:
materialize unique eligible candidate documents once where a branch expands chunks.

## Interface contracts

| Contract ID | Producer | Consumer | Change | Failure |
|---|---|---|---|---|
| IC073-001 |CLI/MCP/REST/Python |shared validator/readers |optional `filter` JSON; CLI `--filter-json` or `--filter-file` exclusive |explicit malformed/unsupported/over-budget; no stripped fallback |
| IC073-002 |MCP/CLI/REST save |store.save_document |optional `metadata` mapping of registry keys |atomic rejection/secret removal; no scope promotion |
| IC073-003 |registry |schema read tool/client discovery |030 typed_metadata1 capability +schema |older server refuses supplied new options; omitted remains compatible |
| IC073-004 |normalizer |SQL/direct readers/child |normalized AST/type/field descriptors only |bounded, no SQL from client, restored caller state |
| IC073-005 |upgrade039 |schema check/operator restore |additive helper/index/function manifest |old029 signatures retained; no canonical rewrite |

`filter` is a Python/library keyword via keyword-only arguments, not a field
added to existing positional calls. Transport adapters may name internal locals
`metadata_filter` to avoid shadowing builtins. Central queued requests retain one
normalized argument; no whole-registry payload or credential enters the spool.

## Compatibility and recovery

030/schema039, source029/schema038. Preserve001..038 byte-for-byte. Archived029
rehearsal must contain multiple users/projects/domains, unknown/global scopes,
confirmed/unconfirmed/superseded/withdrawn claims, pins, old jobs, application-free
and typed fixtures. Verify original table hashes/ACLs/owners/sequences/vectors
before and after interrupted/retried upgrade. Independently restore source and
target under an owner without superuser rights. Old029 readers/writer still work;
new typed requests refuse029 servers. Code rollback removes registry configuration
and stops typed requests, retaining039 and namespaced data; no data restore unless
an explicitly isolated verified target is selected. Production metadata remains
unchanged and no bulk adoption/re-embedding is part of deployment.

## Tests and practical evidence

1. Freeze red unit contracts: registry/parser/type truth tables, all bounds,
   invalid stored values and SQL/reference parity. Red before runtime changes.
2. RLS exact-oracle matrix: owner/reader/admin, reused generic plans, revoked
   rights, mandatory source/review/as_of/lifecycle gates, graph bridges and
   supersession dependencies unaffected by filters.
3. Candidate matrix: raw/contextual/planned/managed lexical+vector, small/large
   scopes, ANN continuation/exhaustion and match-before-limit mutation.
4. Actual CLI/MCP/REST/SDK same AST, authenticated queued work, readonly save
   refusal, child research propagation, filtered context/summary/count/export and
   unfiltered legacy equality. No unknown filter can fall through.
5. Populated029 upgrade/interrupt/retry/old-client/owner/restore/code rollback.
6. Root practical rehearsal: approved Linux production references this month;
   OR labels plus NOT and null/missing/list behavior; selective retrieval behind
   excluded nearest chunks. Record code/input/log hashes, samples, parity and
   p50/p95 serial overhead under RLS. No throughput/SLA claim or paid model call.
7. Independent complete bounded review, as-built derived success/recovery tests,
   focused affected selection, docs/Node/lock/wheel. One full nearPR; mechanical
   expectation/doc fixes get focused checks instead of repeating an unchanged
   runtime suite. Never turn a failed full log into a pass.

## Dependencies and ownership

Root owns spec/plan/tasks/UML/readme playbook/evidence, integration and delivery.
One serial implementation writer owns runtime/039/tests and release labels, no
concurrent mutable database or overlapping writers. An independent reviewer owns
only a named ignored report/private synthetic resources. No separate worktree is
needed: already isolated on `feat/typed-metadata-filters-73`.

## Architecture findings and questions

Design analysis must answer: exact placement before every LIMIT; optional
selection versus mandatory truth dependencies; filtered cache/pin/source behavior;
server registry/client compatibility and per-operation restoration;039/old029
upgrade/rollback. Record AF073 findings and the smallest relevant flow diagram
under `docs/uml/` before tasks. Do not implement a security-policy rewrite as a
shortcut. If the measured bounded design cannot retain exact results, return the
specific boundary to planning rather than silently narrow scope.

## Supporting artifacts and playbooks

No generic research/data-model/quickstart file is needed: concrete schema/AST and
compatibility decisions live above; PB07301 supplies user procedures. One justified
formal filter grammar may be extracted if needed, not duplicated across documents.

PB07301 system deliverable `docs/metadata-filters.md`, root owner, source
US-001..003/FR-001..008, ready before PR. Rehearse registration, inspected schema,
audited labels, same local/central filters, refusal and unchanged next operation,
populated029 upgrade and failed-recovery decision. Independent playbook review
and actual synthetic CLI/API evidence required; changes to existing install do
not authorize automatic metadata adoption. Development operations use the
existing isolated DB/upgrade harness, plus owned cleanup; no new permanent
framework or second benchmarking protocol is justified.


## Implementation evidence

Runtime checkpoint `837517b` implements S073-1. Root independently reviewed the
complete runtime/tests/SQL diff and compared all nine SQL sibling bodies against
the actual predecessors: no C/H/M finding. The bounded contextual ANN continuation
coverage gap is Low and explicitly retained. Root rehearsal `frozen-837517b-3`
passed76/76 assertions on522 synthetic originals,13 manually expected sets and
actual CLI/REST/MCP; source tables remained unchanged. The linked verification
record reports30 samples/arm for each of three examples, including slower
filtered cases and the sequential scan. Neither the plan nor the record claims
an index acceleration or production latency result.
