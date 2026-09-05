# Issue #4 — deployment and source recovery

The additive `009_mining_batches.sql` migration preserves existing documents,
queue rows and legacy UUID cursors. Take a normal `rag backup`, apply `rag init-db`
with the new checkout before running its worker, then run `rag status`.
A second migration invocation applies nothing. Keep the previous code and backup
until the new worker has processed a normal new session successfully.

## New input

Mining uses versioned source-prefix/character-offset cursors. `max_digest_chars`
bounds one window and `per_block_chars` bounds an event's contribution in a window;
remaining eligible prose is resumed, not discarded. Incomplete or malformed records
are not acknowledged. Normal tool-result bodies and non-memory tool inputs remain
excluded. Claude messages and native Codex response-item messages are supported;
duplicate event-message notifications do not duplicate Codex prose. Existing
continuity head/tail digests are unchanged.

An accepted, normalized, secret-stripped extraction is persisted before application.
All document saves, edge/audit effects and its applied marker commit together. A
process death before commit leaves an unapplied accepted batch; normal job recovery
reuses it without another provider call. A death after commit reuses the stored
result. Each document/audit-only item has a stable batch and item identity. Existing
failure attempt limits still apply to repeated failures; exhausting them is visible,
not a claim that the batch completed. Application redoes local embeddings on retry,
but cannot create duplicate committed batch effects.

Each worker claim handles one window. A successful window with remainder puts the
same job back into pending and resets its failure-attempt count. The existing drain
limit bounds work; remaining work is picked up by the next scheduled/hook drain.
An enqueue during processing requests another pass, so input appended while a model
call runs is not lost. `rag status --json` includes recent window input/output cursors,
accepted-but-unapplied count and source warnings, without extraction bodies.

## Existing or damaged input

- A uniquely matching legacy UUID can be used as the initial boundary. Subsequent
  progress uses the new cursor. Missing or repeated legacy identities require review;
  the miner does not guess which source range was already consumed.
- A changed/truncated/rotated source prefix produces a visible recovery error.
  Restore the original source bytes from the retained original/backup if available;
  repairing an incomplete trailing record permits normal continuation. Preserve the
  failed queue row and any accepted batch as evidence. Do not manually change cursor
  hashes, UUIDs, batch rows or document metadata to bypass validation.
- This upgrade cannot identify text already skipped by the old digest cap. Historical
  backfill is a separate, explicitly scoped operation: first establish a source/time
  cohort and before-state backup, inspect already-mined sources, choose an isolated
  replay/compare plan and obtain authorization for any historical provider processing.
  A replay must reconcile existing documents through the audited gateway. Do not
  reset all old queue cursors or assume embedding similarity provides exactly-once
  historical recovery. No historical backfill is performed by this release.
- Rolling code back to a version that treats a new `mw1:` cursor as a UUID is unsafe:
  it could fall back to mining the full source. Preserve the database backup and stop
  the affected scheduled worker path before any code/schema rollback; prefer fixing
  forward. Never restore a database backup over newer canonical writes as a routine
  rollback step.

## Verification

Synthetic tests cover the original 80-character example, large individual messages,
partial/malformed JSONL, missing/ambiguous legacy IDs, modified prefixes, identical
and conflicting duplicates, appends during provider calls, unavailable embeddings,
changed hypothetical retry output, repeated completion, and process exits after
both the first and the last document write. Migration and read-only/writer-role
checks use only the dedicated test database. Independent review found and verified
fixes for an ambiguous legacy-cursor case and missing stable audit-item provenance.
