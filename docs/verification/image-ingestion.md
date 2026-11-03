# PB07001: Review and rehearsal evidence

## Completion on both production hosts (0.6.27)

The evidence below is historical unless superseded here. PR98 introduced the
feature, PR101 corrected the bulk-ANN test fixture, and PR102 fixed bounded OCR
execution on macOS. The final merged runtime is `289b8bc` (0.6.27). Independent
reviews accepted the image corrections and the macOS fix with C0/H0/M0; remaining
Low findings stay in [Issue75](https://github.com/phense/agentic-rag/issues/75).

Both production hosts now run 0.6.27 with Deutsch/English Tesseract OCR enabled
and optional vision disabled. Fresh backups of all three stores were independently
restored; original rows, ACLs, owners and sequences were preserved. The stores
contained 24,428 and 24,505 documents on Hetzner and 14,845 on Peter's Mac.
All API health checks returned 200; scoped retrieval and foreign-scope denial
passed. The dashboard principal sees zero documents by policy, so no nonempty
dashboard retrieval is claimed. No existing text or vector was re-encoded and
no production image was ingested. See the [rollout record](../benchmarks/2026-11-03-image-ingestion/production027.json)
and [macOS resource evidence](macos-bounded-ocr.json).

Three inspected examples establish the delivered boundary:

- A synthetic German invoice retains all five required identifiers/amounts in
  real OCR. Native Mac OCR, exact original download, strict review and lexical
  retrieval passed. Before confirmation the transcription is ineligible.
- On Peter's Mac, `qwen3-vl:2b-instruct` correctly described a blue circle on the
  left and a green square on the right. End-to-end ingestion took 4.853 seconds.
- The same model quoted an embedded instruction as document content. Its output
  remained an unreviewed inference; it introduced two spelling errors that the
  real OCR avoided. Invoice and instruction-image ingestion took 4.590 and
  4.253 seconds. This supports OCR-first use, not unrestricted transcription
  accuracy or automatic confirmation.

The [real-model record](../benchmarks/2026-11-03-image-ingestion/mac-real-vision.json)
pins Ollama 0.31.1, the model digest and all synthetic input hashes. It used an
owned daemon/database, real OCR and vision, fixed synthetic embeddings and
internal scoped test principals. Original bytes, SQL/Python review versions and
foreign denial passed for all three images. This was not a fresh central-HTTP
or vector-retrieval evaluation. Two setup failures are retained in the record.
The daemon and disposable databases were removed; 1,930,569,651 bytes of test
model files were deleted. Production vision was never enabled.

The historical full suite remains **2693 passed, 1 failed, 1 skipped**. The
managed-ANN failure was addressed by the independently reviewed fixture-statistics
correction, with its complete module passing at the original SQL budget. The
maintainer approved delivery with focused checks and requested sparse full runs;
no new full-suite pass or universal vision-quality claim is inferred.

## Current correction status (2026-11-03)

The first correction review on `1d1d64d` found four Medium follow-up defects
(client item classification, SQL/Python token divergence, concurrent shared-claim
erasure and reversible quarantine). All four were reproduced by eight regression
failures before their fixes. The second correction uses canonical SQL image tokens,
rechecks every affected claim under locks, rejects normal quarantine reinstatement,
and classifies only explicit per-item remote errors. The fresh affected run passed
143 tests with one existing warning, covering HTTP/MCP, synthesis and both populated
upgrade/independent-restore paths. A new independent delta review and a final full
suite are still required. No production rollout or Mac validation is claimed.

Fresh correction verification on owned PostgreSQL port 55460:

- Backfill regression: 11 passed (six original failures reproduced before the fix).
- Image/privacy integration: 22 passed (secret quarantine, digest/role gates,
  exclusive/shared claims, audit failure rollback and idempotent erasure).
- Transport/backfill/populated upgrade: 20 passed, one existing warning; both
  source versions and independently restored erasure tombstones covered.
- Evidence/research/browser integration: 123 passed, one existing warning.
- Current CLI rehearsal: 38 commands at expected exits, including erasure preview,
  apply, unavailable original, idempotent repeat and recovery from `pre-images.dump`.
  Record: `docs/benchmarks/2026-11-03-image-ingestion/second-correction-rehearsal.json`;
  its input hashes identify the exact code and playbook used before commit.

The historical rehearsal below applies only to the stated earlier artifact hash;
its previous freshness/acceptance wording is superseded by this correction status.
The final suite on 31e17e8 was intentionally interrupted to apply these fixes and
is not a pass. The first suite on 3b7a79c failed (39 failed, 2630 passed, 1 skipped),
including eight browser failures from missing `libatk-1.0.so.0`; the existing private
browser runtime must be supplied through `LD_LIBRARY_PATH` for final verification.


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

## Maintainer-approved delivery, 2026-11-03

Runtime revision `cdfddab` has independent correction review C0/H0/M0, with
Low follow-ups tracked in [Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6605665551).
The full command `python -m pytest -q --tb=short -p no:cacheprovider --durations=20`
finished with exit 1: **2693 passed, 1 failed, 1 skipped**. The failure is
`test_large_generation_ann_and_filters_preserve_second_document`; the test
PostgreSQL log confirms a statement timeout in managed vector retrieval.
The same test then passed individually with the original two-second SQL budget.
The reason for the full-run slowdown remains unconfirmed; this is an open
retrieval-budget reliability issue, not a full-suite pass. Full log SHA256:
`9d5c51112b5f12c820df77f5f0f47df1fe2cf291eec662a5c5cc637f3cdcd54f`.

The maintainer explicitly requested merge of PR98 and upgrades on Hetzner and
Peter's Mac after being informed of this residual failure. A redundant second
full run was interrupted; it does not count as a pass. Further intermediate
verification uses affected tests. No test expectation or SQL timeout was relaxed.

Already verified separately: 143 affected integration tests, 17 documentation
tests, seven Node tests, lock consistency, wheel contents (36 SQL files), an
offline-installed wheel smoke with real Tesseract, and 38 expected CLI rehearsal
outcomes. The two minor playbook clarifications now describe all-skipped batches
and the image-dependent synthesis limitation of code rollback.

Production deployment must preserve original-row hashes, independently restore
its pre-upgrade backup, and check each real host. Upgrading does not re-encode
existing text or vectors. Vision remains opt-in and is not covered by this
delivery's real-model validation. Earlier pending-state sections are historical.
