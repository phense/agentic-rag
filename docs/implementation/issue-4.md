# Issue #4 — resumable, atomic session ingestion

Status: verified and integrated locally; migration 009 active after backup. User authorized issue #4 followed by #3 on 2026-09-05.
Base: fe91b49. Worktree: /private/tmp/agentic-rag-issues-4-3.
Baseline: 625 tests passed in 9.35 seconds against agentic_rag_test.

## Root cause and repair contract

Mining currently truncates a head digest after collecting its final UUID, and
commits each document independently. Continuity deliberately uses lossy head/tail
views and must keep its existing contract.

Add a separate mining-window reader. Its versioned cursor records a verified source
prefix and an offset within redacted eligible prose. Consume bounded pieces until
all eligible text is processed; preserve exclusions for tool results/inputs. Stop
before an incomplete trailing JSONL record. Detect changed/missing cursor sources
and surface recovery errors rather than skip/replay unknown input silently. Legacy
UUID cursors are accepted only when uniquely found. Handle native Codex message
records as well as Claude records; repeated event identities must be consistent.

Persist each accepted extraction with its source start/end positions before applying
it. Apply its documents, suggestions, audit and completion marker in one transaction
through the existing gateway. A death before commit rolls back all effects; a retry
uses the persisted accepted extraction and does not call the model again. A death
after commit observes the completed batch and cannot duplicate its effects. This
bounded atomic-batch approach deliberately avoids partially committed item receipts.
Stable batch/item provenance identifies every logical item.

Keep queue budgets bounded: one window per claim, persist continuation progress,
leave remaining windows pending without consuming failure attempts. Refresh end-of-
source on the next hook enqueue; preserve outage/backoff behavior. Status must expose
accepted-but-unapplied batches and source-window progress without raw content.

## Steps and evidence

- [x] Inspect issues, current source and read-only project instructions.
- [x] Baseline 625 passed; prior synthetic tail loss reproduced.
- [x] Regression tests: bounded window continuation, oversized blocks, malformed tail,
  legacy/missing/rotated cursors, duplicates, append and native Codex records.
- [x] Additive batch migration and atomic write integration; crash/replay regressions.
- [x] Queue continuation/status, privilege/migration tests, full suite: 643 passed in 10.21 seconds.
- [x] Recovery documentation and independent review; both Important findings fixed.
- [x] Local integration and migration/status read-back.
- [ ] Remote publication and issue closure.
- [ ] Then issue #3: isolated bilingual quality benchmark, actual baseline report.

## Operational boundary

No historical reprocessing is authorized by this change. The old UUID cursor may
already have skipped content; do not pretend the new code reconstructs it. Document
explicitly scoped recovery. Test with synthetic data in the dedicated test database;
keep canonical data and existing host integrations untouched during development.

## Continuity tool compatibility

The project-backlog continuity run was initialized at .engineering-method/runs/RAG-004.
The installed recover command cannot parse this repository's pre-existing numbered
BACKLOG.md (reports no project-key task IDs). Do not migrate or rewrite the backlog
merely to satisfy tooling. On resumption verify this plan, current Git diff, issue
status and listed tests directly; use the state/event APIs for checkpoints, and do
not claim automated recover succeeded. Independent reviewer /root/review_issue4 is
complete: both Important findings were regression-tested and fixed.
