# Feature Specification: Source-backed local image ingestion

## Stable work ID

- Feature ID: RAG-070; stable roadmap ID 6.12; Issue [70](https://github.com/phense/agentic-rag/issues/70).
- Status: Approved direction; implementation and acceptance pending.
- Source request: screenshots and receipts become searchable knowledge, with Tesseract OCR and optional local Ollama interpretation; preserve existing production data on Hetzner and Peter's Mac.

## User scenarios

### US-001: Inspect and retain a local image (Priority: P1)

A writer explicitly submits a supported image. They inspect retained original bytes,
recognized words and their locations, engine identity and warnings. After existing
review rules permit publication, a reader finds the derived text and opens its source.
Independent test: upload a synthetic German receipt, inspect two source regions,
confirm the derived claim and retrieve its original through the authorized interface.

### US-002: Reprocess selected originals safely (Priority: P1)

An operator previews historical candidates and explicitly processes bounded batches.
Retries do not duplicate publications; unavailable original files are reported.
Independent test: interrupt a batch, resume it, update processing settings and prove
that originals, previous derivations and manually reviewed decisions remain intact.

### US-003: Request a local interpretation (Priority: P2)

A writer explicitly enables local interpretation for an image. The result is labeled
as inference, retains model identity and cannot become confirmed user testimony.
Independent test: a misleading diagram and embedded instruction produce bounded
untrusted output, with no permission changes or cloud calls.

## Acceptance criteria

- AC-001: Static PNG/JPEG/WebP bytes are checked for actual type, complete decoding,
  dimensions, pixels, frames and input bounds before any engine call. Unsupported,
  malformed, oversized, animated and decompression-bomb inputs fail without writes.
- AC-002: Local OCR records exact retained bytes digest, engine/language/preprocessing
  identity, recognized text, word regions and warnings. Image interpretations are
  separately labeled and require explicit enablement and a pinned local model identity.
- AC-003: Authorization applies to original bytes, derivations, regions and source IDs
  in local and central operation. Negative controls reveal no foreign IDs, text or
  asset existence. Source withdrawal disables affected retrieval and original access.
- AC-004: All knowledge writes use the audited gateway, secret stripping, evidence,
  validity and review. OCR is a machine transcription, not a user statement; generated
  interpretations are inference. Image instructions never affect policy or tool execution.
  Exact pixels are not text-redacted: warn before upload, withdraw detected-secret
  sources atomically with derivation publication, and provide an operator-only,
  previewable, audited erasure with explicit backup-retention limits.
- AC-005: Same scoped original and processing identity are idempotent across retries
  and concurrent submissions. Changed processing creates a versioned derivation without
  rewriting originals or overwriting manual corrections/review. Atomic failure leaves no
  partial canonical publication. Unknown provider outcomes never report success.
- AC-006: Upgrading performs zero image/model calls and no bulk text/vector rewrite.
  Existing text ingest, old clients, hooks, queued jobs, pins, source history and scopes
  retain behavior. Historical processing is explicit, bounded, previewable and resumable.
- AC-007: Populated isolated copies representing Mac0.6.17/schema029 and Hetzner0.6.23/
  schema035 survive upgrade, interruption/retry and independently restored backups.
  Database and original assets restore consistently; unchanged original-row hashes and
  unaffected vectors match. Rollback boundaries after new image writes are explicit.
- AC-008: Evaluate screenshots, dense German receipts, poor scans, blank images,
  misleading visual context and prompt injection. Report literal fidelity, unsupported
  interpretation, timings, identities and two or three inspected local/central examples.
  Synthetic results do not establish accuracy on arbitrary photographs or an SLA.

## Functional requirements

- FR-001: Image ingestion is opt-in, local inference only; cloud image transfer, arbitrary
  URL fetching, PDF, video, audio and image-vector similarity search are outside this release.
- FR-002: Failures preserve accepted originals and report resumable state. Bound provider
  input/output, runtime, retries and image resource use; do not retry indefinitely.
- FR-003: Retain durable source bytes or an equally durable authorized source reference.
  A path or public URL alone is insufficient. No automatic scanning of personal folders.
- FR-004: Keep original/version, derivation identity and embedding identity separate.
  Preserve Hetzner Q8 and Mac F16 vector spaces; equal dimensions do not imply parity.
- FR-005: A preview distinguishes selected, unchanged, changed, missing and unauthorized
  candidates. Reprocessing refreshes only changed derived representations and rechecks
  dependent claims and caches. A changed reading records its predecessor and a
  `newer_derivation_differs` notice on the older claim, including retrieval metadata;
  its review token changes. Human decisions remain intact until explicit reconciliation,
  and new machine text remains unreviewed. Missing provenance is reported, never guessed.

## Compatibility boundaries

R70-COMP-01..08 in the observed existing-data inventory are mandatory and are covered
by AC-005..007 and FR-002..005. Current inspected base is0.6.24/schema035; actual
production sources are0.6.23/schema035 and0.6.17/schema029. The new feature's PR uses
the next patch version relative to main. Published migrations remain byte-identical.
No production service interruption, migration, batch recoding, merge or deployment is
implied by implementing the feature. Existing text and vectors remain untouched.

## Interface contracts

| ID | Boundary | Inputs | Outputs | Invariants |
|---|---|---|---|---|
| IC-001 | Local file ingestion | Explicit path, domain/project, OCR settings, optional vision | Scoped source/derivation identifiers and review state | Bounded regular file; no URL/symlink/device traversal |
| IC-002 | Central upload | Authenticated bytes and same explicit settings | Same source-backed result | Remote client paths never become server paths; bounded body before decoding |
| IC-003 | Original drilldown | Readable source/document identifier | Original bytes and digest, regions, identities | Authorization and source trust rechecked; no public static asset path |
| IC-004 | Historical processing | Explicit manifest, dry-run/apply, bounded cursor | Candidate dispositions, progress and recoverable result | Zero automatic corpus processing; no guessed original bytes |
| IC-005 | Local OCR/vision seam | Validated image and pinned engine settings | Bounded typed transcription/interpretation | No cloud destination; immutable identities; explicit failure |

## Edge cases

Malformed headers, truncated images, MIME spoofing, animated WebP, huge pixel counts,
blank OCR, low confidence, missing OCR binary/language, mismatched model identity,
endpoint timeout, revoked writer during inference, changed original, duplicate uploads,
concurrent retry, wrong scopes, withdrawn sources, canceled batches and full storage
must return an explicit bounded failure or uncertainty without fabricated evidence.

## Assumptions and unresolved decisions

Tesseract is an optional system dependency; merely upgrading must not require it.
Ollama serves the optional local image model. Its role is separate from bge-m3 search
embeddings. No automatic model download or production enabling is permitted.
Exact media bounds and storage ownership are fixed in the implementation plan.

## Success measures

- SC-001: Zero unauthorized assets, fabricated source quotes or bypassed review gates.
- SC-002: All original bytes/digests and unchanged production representations survive
  populated upgrade/restore, retry and disabled-feature operation.
- SC-003: Exact OCR-region drilldown and two practical search examples work through real
  local and central transports, with independent complete-diff review and fresh tests.

## Playbook obligations

PB07001: system playbook for operators and writers, source AC-003..007. Explain installation,
opt-in OCR/vision, review, upload/drilldown, bounded historical processing, source withdrawal,
backup/restore including originals, actual-source upgrades, failure/recovery and rollback.
Acceptance requires executable local/central examples and populated-copy rehearsals.
