# Feature Specification: Typed metadata filters

## Stable work ID

- Feature ID: `RAG-073`, canonical [Issue73 /6.15](https://github.com/phense/agentic-rag/issues/73).
- Artifact path: `docs/specs/RAG-073-typed-metadata-filters/spec.md`.
- Status: Implemented and independently reviewed; final full-suite and production delivery pending.
- Source request: Continue numbered features automatically after verified72,
  allowing typed application filters while preserving every mandatory boundary.

## User scenarios

### US-001: Select relevant authorized originals (Priority: P1)

A reader requests confirmed Linux references for production updated within an
explicit date interval. One bounded filter combines canonical fields and
registered application labels. Search, graph, context, research, summaries and
filtered listings/counts/export agree on which originals may contribute.
Independent test: compare each surface with a separately enumerated authorized,
source/fact/lifecycle-eligible exact fixture before applying result limits.

### US-002: Add application labels without changing evidence (Priority: P1)

An authorized writer supplies registered typed metadata through the existing
save gateway. Labels never change domain/project ownership, review status or
source trust. Old metadata and original quotations remain intact. New clients
can inspect the server's supported registry; old clients omit the feature.
Independent test: audited save/update, secret removal, refusal and rollback,
plus unchanged behavior with omitted metadata/filter on old and new clients.

### US-003: Explain refusal and recover an existing installation (Priority: P2)

An operator validates a registry, observes bounded refusals, upgrades a populated
029 installation and safely removes new configuration on rollback. No canonical
text/vector recoding or background relabeling occurs.
Independent test: interrupted upgrade/retry, independent source/target restores,
old readers/writer and rollback retaining additive metadata.

## Acceptance criteria

- AC-001: Filtered search returns only exact authorized matches, including highly
  selective matches behind more than256 nearer excluded vector chunks. Eligibility
  and optional filters run before candidate/ranking limits; a bounded exact fallback
  supplies the required candidate set or returns an explicit bounded failure.
- AC-002: Identical AST semantics apply to lexical/hybrid/contextual/managed
  indexes, graph nodes and both edge endpoints, research expansion, summary and
  context references, filtered counts and original export. No post-LIMIT filtering
  may silently report a complete subset. Anonymous pins/aggregate caches must not
  inject unfiltered source text into a filtered result.
- AC-003: Nested AND/OR/NOT and every supported leaf agree with an independent
  truth-table oracle for null, missing, mismatched stored types, Unicode, lists,
  date/timezone, malformed and injection cases. Unknown operators/fields/versions,
  excessive work and incompatible clients fail explicitly, never run unfiltered.
- AC-004: Every filtered result is a subset of the same request's authorized,
  existing mandatory eligible set. Current revocation, unknown/global/project
  scope, withdrawn/expired/unconfirmed sources, view/as_of/history and original
  spans retain existing meaning. Filter selection never affects truth evaluation
  of superseding sources or other dependencies.
- AC-005: Optional metadata writes validate the configured schema and use the
  existing audited gateway, merge only application fields and preserve reserved
  metadata. Failed validation/audit leaves all rows unchanged. Read-only principals
  cannot write; labels cannot confirm a claim or broaden scope.
- AC-006: REST/CLI/MCP/Python entry points accept the same versioned JSON AST;
  schema inspection reports limits and registry without enumerating data. Old
  clients and omitted options keep their existing contract. A filtered request to
  an older server is refused rather than silently stripped.
- AC-007: Publish2–3 practical before/after cases with exact input/code hashes,
  samples, result parity and p50/p95 overhead on a representative synthetic store,
  with/without registered application labels and under a real RLS reader. Report
  index plans and timeout/budget failures honestly; no universal SLA is inferred.
- AC-008: Populated029 upgrade applies only additive039; retry, restricted owner,
  old code, independent backups/restores and code rollback preserve original rows,
  users/domains/scopes/pins/claims/jobs/vectors/ACLs/sequences. Verify both production
  hosts separately after merge, with no automatic relabeling or recoding.

## Functional requirements

- FR-001: Contract `metadata-filter-v1` uses `{version:1,where:NODE}`. A NODE is
  exactly one logical node `{and:[NODE,...]}`, `{or:[NODE,...]}`, `{not:NODE}` or
  one leaf `{field:NAME,op:OP,value:VALUE}`; exists/is_null use a boolean value.
  Empty groups, unknown/extra keys and duplicate JSON keys are invalid. No raw
  SQL, JSONPath, regex, arbitrary field traversal or implicit coercion is accepted.
- FR-002: Fixed read-only fields include dtype, status, slug, created_at,
  updated_at, verified_at and claim review_state. Domain/project and authorization
  identities remain existing explicit selectors, not metadata aliases. The
  bounded operator registry defines at most32 flat `app.NAME` fields and types;
  at most64 ASCII identifier bytes per name. Default registry is empty. Data
  values and scope identities are never inferred from registry names.
- FR-003: Supported types are string, finite JSON number (excluding booleans),
  boolean, ISO date, offset-aware timestamp, and homogeneous scalar string/number/
  boolean lists. Dates are calendar dates; timestamps compare instants normalized
  to UTC. Unzoned timestamps and nonfinite numbers are rejected. Application data
  uses a versioned namespaced envelope inside documents.meta; existing unrelated
  keys are retained and are not silently adopted or rewritten.
- FR-004: The operator/type matrix includes eq/ne and scalar in/nin, ordering for
  numbers/date/timestamp, literal string prefix/contains, list has_any/has_all,
  exists and is_null. No regex, locale-dependent ordering or casefold inference.
  Strings compare exact Unicode codepoints. Literal pattern metacharacters stay
  literal. Unsupported type/operator combinations are errors before retrieval.
- FR-005: Missing, JSON null, wrong-type and present-valid are distinct. exists
  checks presence including null; is_null matches only explicit null. Other
  leaves require present nonnull correctly typed data; ne/nin do not match absent
  values. Logical NOT complements the leaf's boolean result within the mandatory
  eligible set, so NOT(eq) can include missing values. No SQL UNKNOWN escapes.
- FR-006: Maximum encoded AST16KiB, depth6,32 leaves/64 total nodes,32 values per
  list, scalar string1024 bytes and pattern256 bytes. Metadata application payload
  max16KiB/32 keys, lists max32 items. Enforce before persistence/network/model
  work and defensively at the SQL boundary. Preserve shorter existing deadlines;
  filtered SQL has a finite maximum5s and bounded candidate/document work. A
  timeout or unsupported expensive operation is explicit and never retries as
  unfiltered. Avoid unbounded dimension/index creation.
- FR-007: One registry and normalization implementation serves local/central
  reads and saves. Caller data cannot change the configured registry. The filter
  identity participates in any result/profile/cache key or filtered requests use
  a source-validated uncached path. Query-vector reuse may remain because a query
  embedding is not a result cache and authority is checked again.
- FR-008: No new data privileges, definer data lookup, leakproof marker, permission
  cache or altered RLS policy is permitted. Filter context is request-local,
  restored on success/failure and propagated explicitly to the research child;
  it cannot affect a later write or another request/connection.

## Compatibility boundaries

Existing029/schema038 is the deployed source on Hetzner and Peter Mac. Published
001–038 remain byte-identical. Version030 is exactly one patch higher. New
configuration is optional; no filter/metadata option means old observable behavior
and no extra provider call. New metadata is advisory application data, never
canonical evidence. Old code may ignore it on rollback; new typed requests require
030 and are rejected against old servers. Retain additive039 on code rollback;
stop typed requests, remove new config and restore029 code, not production rows.
No new daemon, service, provider, automatic backfill or third-party dependency.

## Interface contracts

| Contract ID | Boundary | Inputs | Outputs | Errors or invariants |
|---|---|---|---|---|
| IC073-001 | Query surfaces | Optional filter JSON +existing selectors | Narrowed original-source results, existing shape | Value-free invalid_filter/unsupported_filter/filter_budget; no silent fallback |
| IC073-002 | Save gateway | Optional registered application metadata | Audited ordinary SaveResult | Reserved metadata/scope untouched; atomic validation |
| IC073-003 | Schema inspection | Authenticated ordinary read, no data query | Version/types/operators/registry/limits | No contents, counts, identities or credentials |
| IC073-004 | Candidate selection | Validated filter under current scope | Eligible match set before LIMIT | Mandatory source/truth checks evaluate without optional-filter influence |
| IC073-005 | Upgrade | Populated029 with paused writers and verified dump |039 plus preservation/restore evidence | No canonical rewrites; safe retry/code rollback |

## Edge cases

Missing filters vs empty JSON; wildcard literal `*`; empty lists; NOT on absent
fields; false vs0; exponent/nonfinite/huge numbers; timezone-equivalent instants;
invalid stored historical types; duplicate JSON keys; revoked reused generic
plans; graph bridge excluded by filter; cached summary mixing permitted and
nonmatching sources; anonymous pins; mixed old/new processes; budget exhaustion
before export; supplied metadata resembling domain/project/user privileges.

## Assumptions and unresolved decisions

The user has authorized end-to-end numbered delivery and production updates.
Routine implementation defaults above do not require another method choice.
Application field declarations are operator configuration, not user-defined SQL
or an unlimited indexing service. Existing flat historical meta is inventoried
and retained; explicit later audited adoption is separate. No unresolved user
scope/security choice remains; design must prove integration before coding.

The Mem0 [OSS reference](https://docs.mem0.ai/open-source/features/metadata-filtering)
was reread2026-11-04. It documents backend-dependent wildcard/operator and
get_all/search differences. This implementation specifies one explicit contract
instead; no Mem0 parity or performance superiority is claimed.

## Success measures

- SC-001: Zero differences from the independent boolean/exact authorized oracle;
  zero foreign IDs or snippets under every tested filter/revocation surface.
- SC-002: Every supplied invalid/unsupported/budget case fails explicitly and
  leaves data, caller settings and later unfiltered operations unchanged.
- SC-003: All registered-type saves and populated029/restore/old-client cases
  preserve existing canonical state; practical overhead is measured, not invented.

## Playbook obligations

PB07301, `docs/metadata-filters.md`: operator/developer typed schema inspection,
registration, audited labels and2–3 practical queries; invalid/unindexed/budget
refusal; populated029 upgrade, rollback and failed-restore recovery. Source
FR-001..008/US-001..003, audience operators and client authors. Acceptance requires
an independently reviewed executable local/central rehearsal and synthetic exact
parity, with no production relabeling or private content in public evidence.
