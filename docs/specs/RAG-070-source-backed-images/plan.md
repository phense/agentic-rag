# Implementation Plan: Source-backed local image ingestion

## Stable work ID

- Feature ID: RAG-070; specification: [spec.md](spec.md).
- Status: Design candidate for bounded architecture gate before implementation tasks.

## Summary

Add an optional bounded media pipeline beside text ingestion. Retain original bytes
inside PostgreSQL under document-backed RLS so the existing verified database backup
also captures images atomically. Keep OCR machine transcription and optional vision
interpretation distinct and use existing audited document/evidence/review gateways.
No changed bge-m3 model, global reindex, filesystem crawl or automatic backfill.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Existing installation | Recorded live 0.6.17/029 and0.6.23/035 stores | Both populated upgrade/restore sources required |
| Local-only inference | Maintainer direction and isolated OCR comparison | Tesseract primary, Ollama optional; no cloud |
| Audited writes / RLS | store.py, evidence.py, service/context.py | New asset writes need canonical audited gateway and invoker RLS |
| Independent complete review | AGENTS.md | Required before delivery |
| Version and rollout | AGENTS.md | Next patch at PR time; specific merge and rollout separate |

## Technical context

Python3.13, psycopg3, PostgreSQL17/pgvector, Starlette, CLI/MCP and local/central clients.
Current pipeline accepts text events only. Optional Pillow decoding and external
Tesseract binary/language files are needed; text-only upgrades must still work without
OCR installed. Available CPU hardware has no GPU; optional vision is bounded and off.

## Data and ownership candidate

- Add an unreleased additive migration after035; do not edit001..035. Store original
  bytea, SHA256, detected MIME, dimensions and derivation metadata under a canonical
  document/source anchor. Maximum original 4MiB, maximum decoded pixels16M, one static
  frame, maximum side8192px. Decode in a bounded owned subprocess; cap output and time.
- Original/source namespace includes domain/project and, centrally, authenticated owner
  namespace. Never deduplicate sensitive assets across unrelated authority boundaries.
- Asset access policies recheck the readable anchor and source trust. Assets remain
  inspectable before claim confirmation; withdrawal must prevent normal asset reads.
  No security-definer shortcut or public filesystem route.
- Identity covers original SHA256, pipeline version, engine version, language-data
  hashes and preprocessing; optional vision adds exact model digest. Engine identity
  changes create a new derivation and retain reviewed history; do not silently activate
  new inferred facts or mutate old human decisions.
- Publish through store.save_document/evidence gateways in one audited transaction.
  OCR role is machine/unknown and interpretation kind is inference. Canonical source
  support must point to the original and retained regions; never pretend OCR is an
  exact byte quotation from pixels. Existing confirmation is required where applicable.
- Recheck authorization and source validity at commit. Provider/decode work precedes
  publication; deterministic scoped keys and locking guard concurrent retries. An
  idempotent retry must not reset withdrawn trust or reviewed decisions.

## Interfaces

| ID | Producer / consumer | Change | Failure behavior |
|---|---|---|---|
| IC-001 | CLI -> image gateway | Explicit bounded regular-file input | Unsupported/unavailable before writes |
| IC-002 | RemoteClient -> central authorized upload | Bounded encoded bytes, never server filesystem paths | Auth/rate/budget before inference; no raw image logging |
| IC-003 | CLI/MCP/API -> asset reader | Bounded original/regions drilldown | Uniform unavailable for absent/foreign/withdrawn |
| IC-004 | Operator -> manifest processor | Dry-run first; explicit batches and durable progress | Report missing/changed; retry without duplicate writes |
| IC-005 | Validated media -> engine adapters | Tesseract text+TSV, optional local Ollama image interpretation | Finite deadline/output; verify model identity before/after |

Reuse the current transport/auth envelope where safe. A separate bounded upload route
may be necessary to enforce body limits before JSON/base64 allocation. Do not add images
to existing unbounded trace/error payloads. No implicit read-only MCP write capability.

## Dependencies and tests

Tesseract is opt-in with explicit binary and traineddata directory. Do not invoke a shell
for inference. Pin/report engine/language identity; apply OMP thread and output bounds.
Ollama image inference is loopback-only for this release, disabled by default, with pinned
model digest, resource admission, finite timeout and no automatic download/fallback to cloud.

Tests precede implementation: real image decoding; bounded external-engine seam; literal
region geometry; blank/poor/injection fixtures; real gateway/RLS/HTTP/CLI transport; concurrent
retry; source withdrawal; revoked writer; audit failure; new processing identity; explicit
historical backfill. Mock only provider/inference where required; retain actual SQL/auth.

## Compatibility and recovery

Upgrade adds empty structures only. Originals in PostgreSQL keep backup consistency and
avoid a second mutable filesystem store. Update restore inventory/schema-validation
allowlists as needed. Verify physical original hashes and old-row hashes after independent
restore. Use archived0.6.17 and0.6.23 fixtures on owned isolated databases; never mutate live
production to rehearse. Code rollback retains additive tables/data; old clients ignore them.
Never advertise schema downgrade after new image writes. Missing originals remain reported.

## Architecture questions

1. Can asset policies reuse document/source visibility without leaking IDs or recursively
   evaluating policies? Include reprocessing, source withdrawal and reviewed claims.
2. Is the upload/decode/inference/publication sequence bounded and atomic under concurrent
   retries and authorization changes? Keep raw bytes out of logs and public evidence.
3. How does optional processing preserve source/model identity, history and vector-space
   independence across actual-source upgrade/restore and old/new client coexistence?

Design-time architecture review must answer these before final task generation and settle
concrete storage/transport details. It may simplify the candidate while preserving all ACs.

## Implementation structure

One cohesive core slice owns media validation, engine adapters, additive asset schema,
canonical publication and relevant fixtures. A dependent integration slice owns CLI/central
transport, bounded backfill and source drilldown. A final slice owns populated upgrades,
playbook, full verification, as-built reconciliation and independent complete-diff review.
Serialize writers where interfaces overlap. Do not delegate tiny mutually dependent patches.

## Playbook obligations

PB07001 system playbook: docs/image-ingestion.md, operator/writer audience, AC-003..007.
Author/review/rehearse before delivery. Development rehearsals use existing isolated database
and verified-backup procedures plus the new original-byte integrity checks; no new production
operation is authorized. Resource and original-data integrity gates remain unchanged.

## Architecture gate outcome (2026-11-03)

The three questions are answered by AF070-001..007 (`docs/uml/findings.md`) and the
views in `docs/uml/image-ingestion-70.md`. Simplifications that keep every AC:

- Originals carry an immutable copy of their write scope and use the SQL035
  visibility predicate directly; derivations are visible only through originals.
  Word regions are a bounded JSON column on the derivation, not a third table.
- One knowledge source per scoped original (`image1:` namespace, centrally under the
  authenticated `svc1:` owner namespace). Existing strict source-state review is the
  only withdrawal/reinstatement path. Claims use dtype `source`; OCR is `stated` with
  `complete=false` spans and interpretation is `inference`, both from role `unknown`.
- Two transactions: accept a validated original, then publish one derivation. Engine
  work runs between them without locks. Failed engine work is reported, not stored.
- Historical processing is a manifest of local files or retained original IDs with a
  private cursor file; PostgreSQL idempotency keys, not the cursor, guarantee safety.
- Central upload is a raw-body route; the client never sends a path. MCP gains only
  the read tool `memory_image` (metadata and regions, no bytes, no write tool).
- Configuration section `[images]` is disabled by default; Pillow is the optional
  `images` extra; Tesseract and Ollama remain external, explicitly configured tools.
