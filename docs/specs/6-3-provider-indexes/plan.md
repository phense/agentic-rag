# Implementation Plan: Providers and recoverable embedding indexes

## Stable work ID

RAG-061 — [spec.md](spec.md), source `8e521a7`, target 0.6.14/schema027.

## Summary and repository evidence

Keep the canonical PostgreSQL store and existing fixed1024 columns intact. Add
sidecar generations with immutable descriptors and dimension-independent halfvec
values. Never copy untagged legacy vectors into a verified generation.
`embed.py` is the inference chokepoint; `llm.py` owns extraction independently.
`search.py` and mining's semantic duplicate lookup currently consume untagged raw
vectors. New managed reads must bypass every legacy vector branch, including
contextual vectors. Lexical context remains usable. Existing SQL016 establishes
before-limit scope/time filters and document diversity; retain those invariants.

## Project gates

| Gate | Evidence / response | Result |
|---|---|---|
| Single store and audited writes | AGENTS.md; derivative SQL gateway plus audit | Required |
| Existing install | Additive027; populated026 restore/hash/ACL rehearsal | Required |
| Independent review | Entire bounded diff, then changed fix ranges | Required |
| Provider privacy | Offline inspect; explicit probe/build; protected references | Required |
| Patch/docs | pyproject/lock/badge/changelog 0.6.14; PB061-OPS | Required |

## Technical context and decisions

Python3.13, psycopg3, PostgreSQL17, pgvector halfvec. Supported managed dimensions
1–4000; cosine distance and explicit `none`/`l2` normalization; raw-v1 initial
representation. Existing contextual index is retained separately and never mixed
with managed vectors. Bounded exact/ANN candidate planning must preserve filtering
and query time limits; an inability to plan safely yields lexical results.

Named embedding profiles are separate from legacy `[embed]`; changing a profile
does not switch the active DB generation. Keep at most three generations, no
automatic deletion. Descriptor identity includes endpoint, provider, model,
revision, dimensions, normalization, metric and representation, not credential
material. Ollama verifies tag SHA256 before and after inference. HTTP adapters
must expose their weaker/stronger revision guarantees and reject unsupported
identity claims. No silent fallback or retry loop; existing finite job retry
policy remains in force, with safe classified diagnostics.

Generation coverage is calculated against current canonical source hashes;
changed/replaced/deleted chunks cannot remain valid accidentally. A bounded batch
infers outside canonical write locks, then locks/rechecks before gateway writes.
Lifecycle operations serialize; cutover holds a short canonical write exclusion
while verifying complete coverage and atomically changing the active pointer.
Retained generations catch up using the same missing/stale selection. Rollback
requires current complete coverage, including writes since activation.

## Compatibility boundaries

Source0.6.13/schema026, additive upgrade, no original-row rewrite. Existing
Claude/Codex auth and legacy local configuration remain supported. Do not infer
historical raw-vector identity from a current alias; managed migration rebuilds
from source. Old clients retain their legacy reads and canonical writes during
transition; mixed-client semantics are documented, not claimed identical.
Downgrade reads legacy indexes, while new canonical knowledge remains present;
managed selection requires the new binary. No production restart in this PR.

## Interface contracts and ownership

| ID | Producer | Consumer | Contract / failure |
|---|---|---|---|
| IC-001 | config.py / providers.py | CLI/index | `EmbeddingProfile`; `cfg.embedding_profiles` mapping; `profile.identity` deterministic descriptor key. |
| IC-002 | providers.py | indexes.py | `resolve_profile(cfg,name)`, metadata-only `verify_identity(profile)`, explicit synthetic `verify_profile(profile)`, `embed_profile(texts,profile)`; `ProviderError(code,retryable)` with safe text. |
| IC-003 | indexes.py / SQL027 | search/mining | `active(conn,cfg)`, `query_vector(...)`, `candidates(...)`, `near_duplicate(...)`; matching descriptor and one generation. |
| IC-004 | index lifecycle | CLI / audited store facade | local-owner-only create/status/build/activate/rollback; finite limits, explicit corpus opt-in, audited transitions. |

Provider adapter implementation precedes index implementation; coordinator owns
CLI, gateway facade, search/mining/service integration, docs, release and evidence.
Shared interfaces are serial, not parallel writes across tightly coupled modules.

## Dependencies and tests

1. Provider unit/MockTransport red-green, then existing config/LLM/cache tests.
2. SQL027 and generation lifecycle real-DB tests: incompatible dimensions,
   source races, two builders/switches, scoped roles, stale rollback, interruption.
3. Search/mining/worker integrations, no mixed legacy/raw/context spaces.
4. Existing-install populated migration/strict restore/original hashes and ACLs.
5. Full Python suite with actual exit artifact, release consistency, independent
   complete-range review; fix and re-review C/H/M before PR.

Use owned stopped test clusters55460–55462 only; private/production DB5432 and
real providers are excluded. Synthetic mocks record request/input counts and
three cold/warm cases, including failure and revision-change cases. No invented
quality gains or full-suite claims from a live process.

## Architecture findings

AF061-001: untagged raw vectors can mix equal-dimension models (search/mining).
AF061-002: source changes during inference/cutover can invalidate coverage.
AF061-003: broad generation tables can bypass scoped service authority.
AF061-004: metadata/credentials cannot themselves prove immutable remote weights.
See `docs/uml/provider-indexes.md` and the RAG-061 section of findings.md.

## Playbook obligations

PB061-OPS (system): `docs/provider-indexes.md`, coordinator, needed before delivery;
independent review plus synthetic CLI interruption/cutover/rollback rehearsal.
PB061-DEV (development): reuse `docs/13-central-service.md` strict backup,
restore, hash/ACL checks for isolated upgrades; confirm applicability before the
rehearsal, never run against production. New generation semantics go in PB061-OPS.
