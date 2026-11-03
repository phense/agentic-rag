# PB07001: Review and rehearsal evidence

## Scope

- Playbook: [PB07001](../image-ingestion.md), self-reviewed SHA-256
  `4e3ebf2fafb651598c970dbb1a71aa54da921bf1cc7d8abfdc6f944fcb8136b5`.
- System: branch `feat/source-backed-vision-70` from base `5426b89`, version 0.6.25,
  migration036; the exact head is the commit that adds this record.
- Requirements: [RAG-070](../specs/RAG-070-source-backed-images/spec.md) AC-001..007,
  tasks T070-001..012.
- Required validation: content inspection plus an isolated CLI rehearsal of every
  part; populated upgrade from both production source lines (0.6.17/schema029,
  0.6.23/schema035).
- Owner: repository maintainer; readiness before enabling `[images]` on any
  production store. Merge and rollout need separate authorization.

## Content review

- Reviewer: the implementing agent (**self-review, not independent**). An
  independent playbook review is still required.
- Date: 2026-11-03.
- Method: each command, option, error code and expected field checked against
  `agentic_rag/image_cli.py`, `image_backfill.py`, `images.py`, `cli.py`
  (`evidence`, `search`), `service/operator.py` and `service/upgrade.py`, then
  executed in the rehearsal below.
- Verdict: **Changes required → resolved in the self-review**; independent
  verdict pending.

| Finding ID | Severity | Evidence | Required change | Disposition |
|---|---|---|---|---|
| PB07001-SR-01 | Important | E2 failed in the first rehearsal with `embedding_identity_mismatch`: `restore-target` compares the target's live embedding-model digest with the manifest. | State the embedding precondition and both mismatch codes in E2. | Resolved in the playbook. |
| PB07001-SR-02 | Important | B5 `rag search "RE-2026-0471"` without filters returned nothing after confirmation because search defaults to the project of the current directory. | Add `--domain`/`--project` and the expected slug line `image-text-...`. | Resolved; rehearsal step B5 found the document. |
| PB07001-SR-03 | Minor | The first A6 check (`rag image show` of a zero UUID) does not prove the feature is enabled; reads are not gated by `enabled`. | Use an empty manifest: dry run proves the OCR identity, apply proves `enabled`. | Resolved; rehearsed as A6-disabled/A6-dry-run/A6-apply. |
| PB07001-SR-04 | Minor | A3/A4 did not name the refusals for active clients or a missing `--writers-stopped`. | Name `worker_still_active`, `database_clients_still_active`, `writers_stopped_confirmation_required`. | Resolved; the missing-confirmation refusal was rehearsed. |
| PB07001-SR-05 | Minor | B4 claimed a notice list that `evidence show` does not emit in that form. | Name the notices observed before review: `review_required`, `machine_transcription`. | Resolved. |

## Rehearsal

- Status: **passed for the listed branches** (CLI rehearsal by the implementing agent).
- Last validated: 2026-11-03 (execution date of the run below).
- Validating party: implementing agent; not independently repeated.
- Environment: administrator-owned PostgreSQL on port 55460, two fresh
  `rag_bench_*` databases created and dropped by the driver; retained Tesseract 5
  runtime under the scratch directory; an owned loopback fake that only reports an
  embedding-model tag digest (embeddings themselves unavailable, so no vectors were
  written). No production database, Ollama or shared service was used.
- Method: [scripts/rehearse_image_playbook.py](../../scripts/rehearse_image_playbook.py)
  seeds a populated store with the archived 0.6.23 code (`c33e11f`: two domains,
  projects, confirmed claims, a fact, a pin, queued work), then runs the playbook's
  `rag` commands as subprocesses. Output:
  [playbook-rehearsal.json](../benchmarks/2026-11-03-image-ingestion/playbook-rehearsal.json)
  (33 steps, all at their expected exit code; local paths replaced by `REPO`/`WORK`).
  Rerun with the committed driver after the migration036 policy change (AF070-013);
  the record names the rehearsed `sql/036_image_ingestion.sql` digest `ee2a233ef3cc9dc4…`.

| Part | Observed result |
|---|---|
| A | Inventory `supported`, 35 migrations; preflight ready; upgrade without `--writers-stopped` refused; upgrade applied up to `036_image_ingestion.sql` with `restore_verified` and `original_rows_unchanged` true and the manifest written; status ok; empty-manifest apply refused with `images_disabled` before enabling; dry run returned a 64-digit OCR identity and apply `complete` after enabling. |
| B | Add: new original, OCR `published`, `unreviewed`; repeat: `existing`, no new original; non-image refused `unsupported_image_type`; show returned the digest, engine identity and the box `[191, 98, 194, 20]` for `RE-2026-0471`; original download matched the digest; existing output path refused; search found nothing before and the slug after strict confirmation. |
| C | References listed the seeded text reference as `reference_only_no_retained_original`; dry run `selected, unchanged, missing, unchanged` with 0 engine calls and 0 writes; cancel → `canceled` with 0 items; `--resume` → `paused` at cursor 2 (`published`, `existing`); next → `complete` (`missing`, `existing`); final call processed nothing. |
| D | Source origin `image_original`; strict withdrawal printed a new source version; show and re-upload then refused with `image_unavailable`; search no longer found the slug. |
| E | Verified backup with both image tables in the manifest; restore into the second empty database `restore_verified`; the restored original matched the source digest. |

The populated upgrade from **both** source lines, including an interrupted
migration, old-code reads after the upgrade, image writes, independent restores
of source and target backups and the code-rollback boundary, is covered by
`tests/service/test_image_upgrade.py` (two parametrized cases, real Tesseract).
Those run the same upgrade functions directly, not through the CLI.

Untested branches and limits:

- Part A through the CLI from 0.6.17 (only 0.6.23 rehearsed by CLI; 0.6.17 by the upgrade test).
- Central client mode for parts B/C through the CLI on a real service host (covered
  by `tests/service/test_image_transport.py` with a real HTTP server on loopback).
- `--vision` with a real Ollama vision model; only an owned loopback fake was used.
- Ctrl-C during a backfill item, a lost cursor file and a concurrent second
  `--apply` (unit-tested, not rehearsed by CLI).
- Production hosts, their Tesseract paths and backup capacity (unresolved local facts).

## Acceptance and freshness

- Draft status: drafted, unresolved local facts listed in *Before starting*.
- Content-review readiness: self-review findings resolved; **independent review open**.
- Agreed validation met: isolated CLI rehearsal and both populated upgrade paths
  passed; vision and production execution not validated.
- Operation readiness: **not ready for production** until an independent review,
  the maintainer's rollout approval and the per-host facts exist.
- Changes since evidence: after the rehearsal only prose changed (term table,
  wording of two outcomes, A6/E2/B5 text matching the rehearsed commands); every
  rehearsed command is unchanged. A later material change to commands or expected
  results makes this rehearsal stale.
- Next action: independent `playbook-review`, then the maintainer decides merge and
  any rollout.
