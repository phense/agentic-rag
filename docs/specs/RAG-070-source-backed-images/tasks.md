# Tasks: RAG-070 source-backed local image ingestion

## Ownership and integration

One implementation writer owns all changed paths (serial; no parallel writers).
Base 5426b89. Design: `docs/uml/image-ingestion-70.md`, AF070-001..007 in
`docs/uml/findings.md`. Independent complete-diff review is arranged by the root
coordinator after delivery and is not claimed by these tasks.

### Slice S070-1: Media core, schema and canonical publication

- [x] T070-001: Red tests for header sniffing and bounded complete decoding of
  PNG/JPEG/WebP; malformed, truncated, spoofed, animated, oversized, max-side and
  decompression-bomb inputs fail before any write. AC-001. Depends: design.
- [x] T070-002: Red tests for the bounded subprocess seam, Tesseract TSV parsing,
  text/word-region geometry, blank/low-confidence uncertainty and immutable identity;
  real Tesseract on the retained private runtime when present. AC-002, IC-005.
- [x] T070-003: Red tests for migration036 (insert-only grants, RLS on own scope
  columns, derivation visibility via originals), schema validation and restore
  inventories. AC-003/006/007. Depends: T070-001.
- [x] T070-004: Red tests for the audited gateway: two-transaction acceptance and
  publication, claim kinds and review gates, idempotent/concurrent retries, changed
  identity preserving review, source withdrawal, audit failure, engine timeout and
  revoked writer. AC-003..005, AF070-002..005. Depends: T070-003.
- [x] T070-005: Implement `image_media.py` (sniff, decode subprocess, bounded run),
  `image_engines.py` (Tesseract, loopback Ollama), migration036, schema/upgrade
  inventory updates and `images.py` gateway until T070-001..004 are green.

### Slice S070-2: Transports, drilldown and historical processing

- [x] T070-006: Red tests for CLI `rag image add/show/original/backfill/references`,
  MCP read tool `memory_image`, central `POST /v1/images`, `/v1/images/status`,
  `GET /v1/images/{id}` and `/original`, RemoteClient upload/download; foreign
  scopes, withdrawal, read-only principals and body caps. AC-003, IC-001..004.
- [x] T070-007: Red tests for manifest preview dispositions, bounded resumable apply,
  cancellation, retry without duplicates and zero image calls when disabled.
  AC-006, FR-005, IC-004.
- [x] T070-008: Implement transports, CLI and backfill until T070-006/007 are green;
  optional vision behind explicit enablement and pinned digest. US-003.

### Slice S070-3: Compatibility, evidence and delivery

- [x] T070-009: Populated isolated 0.6.17/029 and 0.6.23/035 sources: upgrade,
  interruption/retry, image writes, independent source and target restores,
  original-byte and unaffected-row hashes, old-code reads and code rollback with
  retained tables. AC-007, R70-COMP-07/08.
- [x] T070-010: Evaluation on synthetic screenshots, receipts, scans, blank,
  misleading and injection images through real local and central transports;
  literal fidelity, unsupported interpretation, timings and identities. AC-008.
- [x] T070-011: PB07001 `docs/image-ingestion.md` via documentation and playbook
  skills; release 0.6.25 metadata, supported-version labels and future-refusal tests;
  README/CHANGELOG/FEATURES. Depends: T070-008/009.
- [ ] T070-012: As-built reconciliation of UML/findings, affected and full test
  suites, lock/wheel checks, implementation report. Depends: all above.
