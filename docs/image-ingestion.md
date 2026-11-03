---
id: PB07001
title: Ingest, inspect and recover source-backed images
type: task
doc_id: standalone
readers: [operator, writer]
status: drafted
version: 0.6.25 (migration036); upgrade sources 0.6.17/schema029 and 0.6.23/schema035
depends_on: [docs/13-central-service.md, docs/claim-evidence.md, docs/09-maintenance-and-backups.md]
assets: []
last_reviewed: unreviewed
summary: Opt-in local OCR and interpretation of screenshots and receipts with retained originals, review, drilldown, bounded backfill, withdrawal, backup/restore and rollback.
---

# PB07001: Ingest, inspect and recover source-backed images

## Identity and scope

- Class: system playbook (delivered with the feature), with the one-time upgrade
  as its first part.
- Origin: [Issue70](https://github.com/phense/agentic-rag/issues/70),
  [RAG-070 specification](specs/RAG-070-source-backed-images/spec.md) AC-003..007,
  design [image-ingestion-70](uml/image-ingestion-70.md).
- Audience and owner: the **operator** who installs, upgrades and backs up a store,
  and the **writer** who adds and reviews images. The repository maintainer owns
  rollout approval for each production store.
- Target: agentic-rag 0.6.25 with migration036 on one PostgreSQL store. Supported
  upgrade sources are the observed production lines 0.6.17 (schema029, Peter's Mac)
  and 0.6.23 (schema035, Hetzner).
- Readiness deadline: before enabling `[images]` on any production store.
- Last edited: 2026-11-03.
- Review and rehearsal evidence: [verification/image-ingestion.md](verification/image-ingestion.md).
  This document is drafted; it is not reviewed or validated until that record says so.

## What the feature does

You give agentic-rag one image file. It checks that the file really is one static
PNG, JPEG or WebP image, keeps the exact bytes in PostgreSQL, and runs Tesseract on
your machine to read the text and the position of every word. The text becomes a
memory that waits for your review. Optionally a local Ollama model also describes
the picture; that description is stored as an inference and also waits for review.

No image goes to a cloud service, and agentic-rag never downloads a URL or scans
a folder. In client mode the bytes go only to your own configured agentic-rag
service, which runs the same local engines. Upgrading does not process any image and does not touch existing text or
search vectors.

| Term | Meaning in this document |
|---|---|
| Store | One agentic-rag PostgreSQL database with its configuration file. |
| Claim | A memory that states something and points to its source; it carries a review state. |
| Original | The retained image bytes, identified by their SHA256 digest and the domain/project they were added to. |
| Derivation | One OCR text or one interpretation of an original, bound to an exact engine identity. |
| Engine identity | Tesseract version, binary digest, language-data digests and settings (page segmentation mode `psm`, engine mode `oem`); for vision the model name and pinned digest. A change creates a new derivation. |
| Region | One recognized word with its box `[left, top, width, height]` in original pixels. |
| Review | The existing claim review (`rag evidence review`). Search and context never return OCR or interpretation claims before a confirmation. |
| Withdrawal | Setting the original's source to `removed` through the existing source-state review. |

## When to use / when not to use

Use this playbook to add screenshots, receipts or scans as reviewable knowledge,
to check a transcription against its original, to process a known list of
historical files, to withdraw an image, and to back up, restore or roll back a
store that holds images.

Do not use it for PDFs, video, audio, image similarity search or photographs whose
meaning matters more than their text; none of these are supported in 0.6.25.
Text references to images that already exist in stored memories (for example
`![scan](scans/r1.png)`) are only candidates. They are never fetched or treated as
retained originals; part C shows how to list them.

## Before starting

- **Code:** agentic-rag 0.6.25 on every host that runs `rag`, `rag service serve`
  or `rag service worker` for this store. Check with
  `python -c "import importlib.metadata as m; print(m.version('agentic-rag'))"`.
- **Decoder (optional extra):** Pillow, installed with the `images` extra, for
  example `uv pip install 'agentic-rag[images]'` in the agentic-rag environment.
  Without it, image commands fail with `decoder_unavailable`; text features are
  unaffected.
- **OCR (optional, external):** a Tesseract 5 binary and its `deu`/`eng`
  `.traineddata` files at paths you choose. agentic-rag never installs or
  downloads them. A private runtime needs its library directory as
  `ocr_library_path`. On macOS use the absolute Homebrew Tesseract and tessdata
  paths; leave `ocr_library_path` unset. Linux resource limits and Homebrew
  operation still require a host rehearsal before Mac enablement.
- **Vision (optional, off by default):** a local Ollama on loopback with the model
  already present. Note its digest from `curl -s http://127.0.0.1:11434/api/tags`.
  agentic-rag never pulls a model and refuses any non-loopback URL.
- **Authority:** an approved maintenance window for part A; write access to the
  target domain/project for part B; operator access to the store host for parts C–E.
- **Unresolved local facts (block readiness of a production store):** the Tesseract
  and language-data (`ocr_tessdata`) paths on that host, the backup directory with enough free space
  (three times the database size), and, if vision is wanted, the exact model and digest.

Configuration, in the file named by `AGENTIC_RAG_CONFIG` (default
`~/.agentic-rag/config.toml`). Every key is optional; `enabled = false` is the default.

```toml
[images]
enabled = true
ocr_command = "/opt/tesseract/usr/bin/tesseract"        # absolute path
ocr_tessdata = "/opt/tesseract/usr/share/tesseract-ocr/5/tessdata"
# ocr_library_path = "/opt/tesseract/usr/lib/x86_64-linux-gnu"
ocr_languages = "deu+eng"
ocr_psm = 6                     # 3, 4, 6 or 11; part of the engine identity
ocr_timeout_seconds = 60
ocr_threads = 1
engine_memory_bytes = 2147483648
# work_dir = "/var/lib/agentic-rag/image-work"           # private temporary files
vision_enabled = false
# vision_url = "http://127.0.0.1:11434"
# vision_model = "<model name>"
# vision_digest = "<64 hex digits from /api/tags>"
```

Fixed limits (not configurable): 4 MiB per image, 8192 pixels per side, 16 million
pixels, one frame, 5000 words, 32000 characters of OCR text and 4000 characters of
interpretation.

## Part A: Upgrade an existing store to 0.6.25

The upgrade adds two empty tables (`image_originals`, `image_derivations`), their
access rules, which limit every service user to the domains and projects they may read. It rewrites no row and calls no image engine.
`SOURCE` is `0.6.17` on Peter's Mac and `0.6.23` on Hetzner; `CONFIG` is the
store's configuration file; `DIR` is a private backup directory.

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| A1 | Operator, store | `rag service --config CONFIG inventory --source-version SOURCE --output DIR/inventory.json` | `"supported": true`; `DIR/inventory.json` lists 29 (0.6.17) or 35 (0.6.23) migrations | `unsupported_source_schema`: stop, escalate |
| A2 | Operator, store | `rag service --config CONFIG preflight --source-version SOURCE --mode local` | `"ready": true` | Resolve the listed blockers first |
| A3 | Operator, every host | Follow the service ownership/restart procedure in [Central service](13-central-service.md). Record the actual systemd unit names on Hetzner and `launchctl print gui/$(id -u)/com.agentic-rag.api` on the Mac before the window. Authority: approved window. Stop `rag service serve`, `rag service worker`, hooks and agent sessions that use this store | No client sessions on the store | A4 refuses with `worker_still_active` or `database_clients_still_active`; stop the remaining client and repeat A4 |
| A4 | Operator, store | Install 0.6.25 code (do not enable `[images]` yet), then `rag service --config CONFIG upgrade --source-version SOURCE --dump DIR/pre-images.dump --apply --writers-stopped` | `"migrations_applied"` ends with `"036_image_ingestion.sql"`; `"restore_verified": true`; `"original_rows_unchanged": true`; `DIR/pre-images.dump.manifest.json` exists | `writers_stopped_confirmation_required`: add `--writers-stopped` after A3. Any other error: the migration rolled back as one transaction; see *Interrupted upgrade* |
| A5 | Operator, store | Restart the services on 0.6.25. `rag service --config CONFIG status` | Status JSON without error | Keep services stopped; escalate with the output |
| A6 | Operator, store | Only after A5, and only if images are wanted on this store: set `[images]` as above and restart `rag service serve`. Run this check on the store host with its local-mode `AGENTIC_RAG_CONFIG`, not a client configuration. Write `{"version": 1, "items": []}` to `DIR/empty.json`, then run `rag image backfill DIR/empty.json --dry-run` and `rag image backfill DIR/empty.json --apply --limit 1` | Dry run: `identities.ocr` is a 64-digit hash (Tesseract found). Apply: `run.state` is `complete` (images enabled) | `ocr_unavailable`: fix `ocr_*`; `images_disabled`: `enabled` was not read from `CONFIG` |

A 0.6.17 store jumps from schema029 to schema036 in one transaction. Old 0.6.17 and
0.6.23 clients keep working against the upgraded schema; they ignore the new tables
and never retrieve unreviewed image claims (rehearsed for both sources).

## Part B: Add, inspect, confirm and find an image (writer)

Local mode works on the store directly. Client mode (`[service] mode = "client"`)
sends the bytes to the central service; your local path never leaves your machine.

**Before B1:** do not submit credentials or information that every reader of the
chosen domain/project may not see. The exact pixels are retained and backed up;
text redaction does not alter the image. OCR cannot reliably detect every secret.
Detected secrets automatically withdraw the image source (`original_quarantined`),
but pixels remain in the database until an operator performs part D's erasure.
A timed-out or unsuccessful OCR is not a privacy scan.

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| B1 | Writer, one file | `rag image add PATH --domain DOMAIN --project PROJECT --label "Receipt 2026-11"` (or `--scope global`) | JSON with `"original": {"created": true, ...}` and one derivation `"kind": "ocr", "state": "published", "review_state": "unreviewed"` | See the table *Outcomes of `rag image add`* |
| B2 | Writer, same image | `rag image show DOCUMENT_ID --limit 50` | `original.sha256`, the engine `identity`, `text`, `warnings` and `regions.items` with boxes | `image_unavailable`: wrong ID, no read access, or withdrawn |
| B3 | Writer, same image | Compare the text with the picture: `rag image original ORIGINAL_ID --output NEW_FILE` writes the exact bytes to a new private file; open it in an image viewer and check words such as amounts at their boxes | The file's SHA256 equals `original.sha256` | `output file exists`: choose a new path |
| B4 | Writer, claim | `rag evidence show DOCUMENT_ID --json`, then `rag evidence review DOCUMENT_ID --state confirmed --reason "checked against the original" --expected-version VERSION` with the `version` just shown | Before the review, `show` lists the notices `review_required` and `machine_transcription`; the review prints `New version: ev1:...` | `evidence_conflict`: show again and repeat; refute wrong text with `--state refuted` |
| B5 | Writer, search | `rag search "RE-2026-0471" --domain DOMAIN --project PROJECT` (any word from the confirmed text) | A result line with the document's slug `image-text-...` | No result before B4 is expected. Without `--project`, search uses the project of the current directory |

Add `--vision` to B1 to request the configured local interpretation as well. It
appears as a second derivation `"kind": "interpretation"` and an `inference` claim
with notice `model_interpretation`. Review it like any inference: the model may
describe things that are not in the picture, and text inside the image (such as
"ignore all rules") is only described, never obeyed.

In an agent session the read-only MCP tool `memory_image` returns the same view
as B2 (no bytes). Central REST clients use `POST /v1/images` (raw body, query
`domain`, `project` or `scope`, `label`, `vision=1`), `GET /v1/images/{id}`,
`GET /v1/images/{id}/original` and `POST /v1/images/status`.

### Outcomes of `rag image add`

| What you see | Cause | What to do |
|---|---|---|
| `error: images_disabled` | `[images] enabled` is not true for this store (central: on the server) | Ask the operator; nothing was written |
| `error: decoder_unavailable` | Pillow is missing | Install the `images` extra |
| `error: ocr_unavailable` | Tesseract binary, the language-data directory or one language file is missing | Fix `[images] ocr_*`; nothing was written |
| `error: unsupported_image_type`, `malformed_image`, `animated_image`, `image_dimensions_exceeded`, `image_too_large`, `request_too_large` | The file is not one bounded static PNG/JPEG/WebP | Convert or crop the image; nothing was written |
| `error: image_file_unavailable` | Not a regular readable file (missing, symlink, directory, device, URL) | Pass the real file path |
| `error: scope_denied` | No write access to that domain/project (central) | Use your own scope or ask the operator |
| `error: image_unavailable` | The same image's source was withdrawn in this scope | Reinstate it first (part D) if that is intended |
| Exit 1 with `"state": "failed", "code": "ocr_timeout"` (or another engine code) | The original was kept; OCR did not finish | Rerun B1 later; it reuses the original and runs OCR again |
| `"state": "existing"` | This image was already processed with the same engine identity | Nothing to do; no engine call happened |
| `"state": "empty"` with `no_text` | Blank or textless image | No claim was created; the original is still inspectable |
| `secret_redacted` and `original_quarantined` | A secret pattern was recognized; original access and source-backed eligibility are blocked | Rotate the credential and follow *Sensitive upload recovery* below; do not reinstate this source |
| `not_found` (404) on an older service | The service has no image API | Upgrade the service first; do not mark the manifest complete |
| `capacity_exceeded` (429) | The service is busy | Retry the same bounded batch later; its cursor is unchanged |
| `authorization_changed` (central) | Your key or rights changed during processing | Nothing was published; retry with valid rights |

## Part C: Process historical files explicitly (operator)

Write a manifest. Relative paths resolve against the manifest's directory; an
`original` item reprocesses a retained original with the current engines (on the
store host only).

```json
{"version": 1, "items": [
  {"path": "receipts/2026-10-01.png", "domain": "finance", "project": "/srv/books"},
  {"path": "/data/screens/error.webp", "domain": "operations", "scope": "global"},
  {"original": "4f0c5c5e-0000-0000-0000-000000000000"}
]}
```

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| C1 | Operator, store | Optional: `rag image references --domain DOMAIN --limit 50` lists stored text that mentions image files | `disposition: reference_only_no_retained_original` per candidate | Use it to locate files for the manifest; never guess missing originals |
| C2 | Operator, manifest | `rag image backfill MANIFEST --dry-run` | Every item is `selected`, `unchanged`, `changed`, `missing`, `invalid`, `unauthorized` or `withdrawn`; `engine_calls: 0`, `writes: 0`; `estimated_engine_items` | Fix paths/scopes and rerun; `ocr_unavailable`: configure OCR first |
| C3 | Operator, manifest | Authority: the dry run was reviewed. `rag image backfill MANIFEST --apply --limit 20` | `run.cursor` advanced by up to 20, `run.state` `paused` or `complete`, one outcome per item | Exit 1 or `run.state: blocked/interrupted`: stop and fix the reported cause. The failed item keeps its cursor; repeat C3 without `--restart`. Check credentials/protocol/schema for service errors; never classify a 500 as a bad file |
| C4 | Operator, manifest | Repeat C3 until `run.state` is `complete`, then repeat C2 | No `selected` or `changed` items remain. Account explicitly for every missing, invalid, unauthorized or withdrawn item | Remaining work: fix its cause and use `--apply --restart --limit 20` to revisit earlier skipped items; existing derivations do not call engines again |

Progress is kept in `~/.agentic-rag/state/image-backfill/<manifest-digest>.json`
(override with `--state-dir`). Only one `--apply` per manifest runs at a time;
a second gets `backfill_already_running`. `counts.failed` counts failed attempts,
not unresolved files; the final preview decides whether processing remains.
A `complete` cursor means the manifest was visited, not that skipped files were processed.

After an engine update, inspect every changed original with `rag image show ORIGINAL_ID`.
Compare the latest OCR text with the older text and the original (B3). A differing
reading records `previous_id`, surfaces `newer_derivation_differs` on the older
claim in image/evidence/search/context metadata, and changes its review token.
It never silently replaces a human confirmation. Check the new claim using B4;
if the old claim is wrong, inspect it afresh and refute it with
`rag evidence review OLD_DOCUMENT_ID --state refuted --reason "superseded reading checked against original" --expected-version VERSION`.
If the new machine reading is wrong, refute the new claim instead. Resolve every
such comparison before declaring that engine-update batch reconciled.

## Part D: Withdraw or reinstate an image (writer or operator)

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| D1 | Writer, claim | `rag evidence show DOCUMENT_ID --json`; note `sources.items[0].source_key` and its `source_version` | The source has `origin: image_original` | `evidence_unavailable`: no access |
| D2 | Writer, source | `rag evidence source-state SOURCE_KEY --state removed --reason "withdrawn by owner" --document DOCUMENT_ID --expected-version SOURCE_VERSION` | New source version printed | `evidence_conflict`: repeat D1 |
| D3 | Writer, image | `rag image show DOCUMENT_ID` | `error: image_unavailable`; OCR and interpretation claims of this image are no longer retrieved | — |

Withdrawal blocks access through agentic-rag; it does not erase the bytes from the
database or from backups. To reinstate, repeat D1–D2 with `--state active`. A
re-upload of a withdrawn image is refused and never resets the withdrawal.

### Sensitive upload recovery (operator on the store host)

1. Stop distributing the image, revoke or rotate any exposed credential, and
   retain only content-free incident identifiers. A `secret_redacted` result
   already withdraws its source. For an undetected sensitive upload, withdraw
   it with D1–D2 first. Do not reactivate it.
2. Preview the exact original with the local store configuration:
   `rag image erase ORIGINAL_ID --expected-sha256 SHA256 --reason "sensitive upload incident"`.
   Check `exclusive_documents` and `shared_documents`. This command is unavailable
   in client mode and to reader/writer roles. It performs no writes without `--apply`.
3. Obtain authority to erase the listed payloads. Repeat step 2 with `--apply`.
   This irreversibly removes original pixels, derivation text/regions and source
   quotes, deletes claims supported exclusively by that image, and preserves
   shared claims and other originals. A content-free source/original tombstone,
   hashes, engine identity and the `image_erase` audit remain. Do not put secrets
   in the reason. An audit/SQL failure rolls everything back: keep the source
   withdrawn and escalate, rather than bypass the gateway with SQL.
4. Check `applied: true`, the single `image_erase` audit event, and
   `rag image original ORIGINAL_ID --output NEW_FILE` returning `image_unavailable`.
   A repeat erase reports `already_erased: true` without another audit or deletion.
5. Restrict and dispose of prior backups, exported originals and external copies
   under the incident's approved retention procedure. Erasure does not alter old
   dumps, PostgreSQL WAL, replicas or filesystem snapshots. A later restore of an
   older backup can restore the secret: keep it isolated, repeat the erasure before
   cutover, and verify a new backup. Shared claim text may still contain information
   from independent sources; review that separately rather than deleting it blindly.

## Part E: Back up, restore and roll back

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| E1 | Operator, store | `rag service --config CONFIG verified-backup --source-version 0.6.25 --output DIR/with-images.dump` | `"restore_verified": true`; `manifest.tables` includes `image_originals` and `image_derivations` | Stop; do not change the store without a verified backup |
| E2 | Operator, new empty target store | Condition: `TARGET` names the same embedding model, and its Ollama serves that model with the digest recorded in the manifest. `rag service --config TARGET restore-target --dump DIR/with-images.dump --manifest DIR/with-images.dump.manifest.json --apply` | `"restore_verified": true`, `"original_rows_unchanged": true` | `target_not_empty`: use an empty database or `--resume`; `embedding_configuration_mismatch` or `embedding_identity_mismatch`: align the target's embedding model first |
| E3 | Operator, restored store | `rag image original ORIGINAL_ID --output NEW_FILE` against the target configuration | Same SHA256 as on the source | Escalate; keep both stores unchanged |

Originals live inside the database, so one dump captures text, vectors and image
bytes consistently; there is no separate image directory to copy.

**Code rollback** to 0.6.24 or older keeps the new tables and every original; old
code ignores them and keeps reading. Older operator tooling (`inventory`,
`upgrade`) refuses a schema newer than it knows (`unsupported_source_schema`):
that is the rollback boundary. There is no schema downgrade after image writes;
the alternative is restoring the part-A dump `DIR/pre-images.dump`, which loses
every change added since that backup. Use this recovery only with explicit
acceptance of that loss; keep the current store untouched for reconciliation:

1. Stop clients and writers using A3 and keep them stopped throughout recovery.
2. Prepare a new empty database and a local `TARGET` configuration with the
   embedding model identity recorded in `DIR/pre-images.dump.manifest.json`.
3. With 0.6.25 operator tooling run
   `rag service --config TARGET restore-target --dump DIR/pre-images.dump --manifest DIR/pre-images.dump.manifest.json --apply`.
   This restores and upgrades the copy; it does not downgrade schema036. Require
   `restore_verified: true` and `original_rows_unchanged: true`. If either is
   absent, keep services stopped and escalate with the manifests. Never restore
   over the failed/current store.
4. Check the restored original-row inventory and original text/vector behavior.
   Record that post-backup writes are absent and reconcile those separately.
   Only after a separate cutover approval point the services at the verified
   target and restart through A5. Keep the previous store and backups protected.
   Code-only rollback can still use the older reader; its operator tooling
   continues to refuse the newer schema, as described above.

## Interruption, recovery and rollback

- *Interrupted upgrade (A4):* the migrations run in one transaction. A killed or
  failed run leaves schema and rows unchanged (rehearsed). Check with
  `rag service --config CONFIG inventory --source-version SOURCE --output DIR/after-failure.json`,
  then repeat A4 with a new `--dump` path.
- *Interrupted add (B1):* if the original was accepted, a rerun returns
  `"created": false` and finishes the missing derivation. Concurrent duplicate
  uploads publish one derivation.
- *Interrupted backfill (C3):* Ctrl-C or SIGTERM finishes the current item, saves
  the cursor and reports `run.state: canceled`; the next C3 continues. To stop a
  run from another shell: `rag image backfill MANIFEST --cancel`; continue later
  with `--apply --resume`. `--restart` starts again at the first item. A lost
  cursor file is safe: already processed items report `existing`.
- *Engine update:* a new Tesseract version, language file or `ocr_psm` is a new
  identity. C2 then reports `changed`; C3 adds new derivations. Earlier
  derivations, reviews and refutations stay; identical text reuses the reviewed claim. Follow the comparison/reconciliation steps after C4 when text differs. The identity currently hashes the executable and traineddata, not dynamically loaded OCR libraries; treat a library update as an operator-triggered reprocessing change and verify the effective engine identity before applying.

## Escalation and preserved evidence

Escalate to the maintainer when A1/A4 fail, when a restored original's digest
differs, or when an image appears in another scope. Keep the command output,
`DIR/*.manifest.json` and the backfill state file. Do not attach original images,
OCR text from private stores or credentials to issues or logs.

## Completion

The upgrade is complete when A4/A5 succeeded and E1 produced a verified backup.
Image use is complete per image when B4 confirmed (or refuted) its claims. A
backfill is complete only after C4 and all changed-reading comparisons are resolved.
Remove authorized temporary image copies separately; sensitive incidents also
require the backup/export retention actions in part D.

## Maintenance and sources

Reassess when the media limits, engine identity fields, schema, `rag image`
options or the service routes change. Sources: `agentic_rag/images.py`,
`image_media.py`, `image_engines.py`, `image_backfill.py`, `image_cli.py`,
`sql/036_image_ingestion.sql`, `service/api.py`. History: 2026-11-03 drafted for 0.6.25.
