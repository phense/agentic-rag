# Feature Specification: Providers and recoverable embedding indexes

## Stable work ID

- Feature ID: `RAG-061`; roadmap step 3/15, [Issue #61](https://github.com/phense/agentic-rag/issues/61).
- Status: Authorized for end-to-end implementation by the maintainer's roadmap request.
- Source baseline: 0.6.13, schema026, commit `8e521a7`.

## User scenarios

### US-001: Choose inference independently (P1)

An operator chooses extraction and embedding separately, sees the destination,
identity, capabilities and bounded usage before any explicit synthetic probe.
Existing Claude/Codex CLI login and local Ollama remain available.

### US-002: Change vector space without losing knowledge (P1)

An operator builds a named, identity-bound index beside the currently searchable
index, resumes interrupted work, checks coverage, then explicitly switches it.
A later rollback includes documents written after the first switch.

### US-003: Continue safely through provider failure (P1)

Unavailable models or credentials produce classified, actionable diagnostics.
Search can use lexical evidence; no other model silently receives the input.

## Acceptance criteria

- AC-001: Existing configuration, CLI login, queued jobs, hooks and service clients
  retain their contracts. Extraction changes do not require reembedding.
- AC-002: Inspection is offline/read-only. Synthetic probes require explicit
  invocation; corpus processing requires explicit permission and a finite batch.
  Inspection shows destination, input/request bounds and possible external egress.
- AC-003: Provider/model/revision, endpoint, dimensions, normalization, metric and
  representation identify a vector space. Same-dimension model changes never reuse
  a managed index or query cache. Invalid, zero or nonfinite vectors are rejected.
- AC-004: A partially built generation cannot activate. Existing documents,
  chunks, IDs, assertions, evidence, pins, audit rows, ACLs and queued work survive
  schema upgrade. Generation writes pass an audited, scope-checked gateway.
- AC-005: A bounded rebuild resumes after interruption; changed sources invalidate
  derived vectors. Concurrent writes cannot make a validated cutover incomplete.
  Each managed search in the new binary uses one space, with eligibility filters
  before candidate limits. Historical untagged legacy reads and old binaries
  remain unverified compatibility behavior; only a managed rebuild verifies them.
- AC-006: Old generations remain searchable and catch-up capable. Rollback refuses
  stale coverage until catch-up, preserving post-cutover canonical writes.
- AC-007: Authentication/configuration, rate limits, transient transport, missing
  models and incompatible responses are distinguishable without leaking secrets
  or request/response bodies. Retries are finite; there is no provider fallback.
- AC-008: Isolated populated 026→027 upgrade, strict restore and original-row
  verification pass. Tests cover deliberately incompatible dimensions, alias
  disappearance, interruption, concurrent edits, scoped search and rollback.
- AC-009: Publish three reproducible synthetic before/after cases with exact
  revisions, sample sizes, cold/warm latency, resource and request/input counts;
  explicitly distinguish them from real-model quality and production evidence.

## Functional requirements

- FR-001: Support a documented initial provider/capability set with protected
  credential references and explicit capability rejection.
- FR-002: Retain the legacy index during opt-in migration; configuration edits
  alone must not select a newly managed index. Never label historical untagged
  vectors as verified under a newly observed model.
- FR-003: Keep a finite number of retained generations; bound rebuild batches,
  input size, inference concurrency, timeouts and SQL work.
- FR-004: Separate operator-only global lifecycle operations from scoped client
  reads/writes. No dashboard dependency or new remote administration API.

## Compatibility boundaries

Schema027 is additive. Existing fixed-size legacy columns and functions remain
available to 0.6.13 clients. Managed generations use their own tagged vectors;
legacy vectors are never imported as verified. Legacy operation stays available
while an explicit managed migration is prepared. Mixed binaries may write
canonical data; source validation must notice those changes too. No automatic
garbage collection, destructive reset, production rollout or live provider test.

## Interface contracts

| ID | Boundary | Contract |
|---|---|---|
| IC-001 | Configuration → provider | Immutable embedding profile descriptor; credential references excluded from identity; validate before network. |
| IC-002 | Provider → index | Verified revision plus finite dimension-correct vectors; classified errors, bounded calls, no fallback. |
| IC-003 | Index → search | One selected generation and matching profile; source-current eligible candidates only; safe lexical degradation. |
| IC-004 | Operator → lifecycle | Explicit create/build/status/activate/rollback; idempotent resume, global local-owner authority, audited transitions. |

## Edge cases

Model replaced during inference; equal dimensions but different revision; empty
corpus; deleted/replaced chunks; metadata-only scope changes; partial documents;
simultaneous builders/switches; stale generations after rollback; missing secret;
credential rotation; old binary writing after cutover; scoped readers.

## Assumptions and unresolved decisions

Initial adapters are deliberately finite: existing Claude/Codex CLI extraction,
Ollama embeddings, plus explicitly configured HTTP capabilities where the provider
can meet the identity contract. Provider identity guarantees must be stated
honestly; an operator label alone is not proof of remote immutable weights.
Related #15/#27/#34 remain independently tracked. #68 live acceptance remains open.

## Success measures

SC-001: zero changed original-row hashes after additive upgrade and verified restore.
SC-002: zero mixed-space managed results across two dimensions and equal-dimension revisions.
SC-003: zero corpus calls during inspection/probes; explicit batches never exceed bounds.
SC-004: all Critical/High/Medium findings resolved before PR; Low findings linked in #75.

## Playbook obligations

PB061-OPS: English operator guide for protected configuration, explicit egress,
bounded rebuild, cutover, catch-up rollback and failure recovery. Audience: local
installation/service operators. Acceptance: actual CLI examples and isolated
success/interruption/rollback rehearsal; production deployment remains separate.
