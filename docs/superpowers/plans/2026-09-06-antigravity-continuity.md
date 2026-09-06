# Antigravity Continuity Implementation Plan

**Goal:** Give Antigravity CLI (`agy`) sessions the same durable continuity
across compaction that Codex and Claude Code have, bound to Antigravity's own
hook contract (SessionStart/PreInvocation/Stop, `injectSteps`, camelCase
payloads, no compaction events).

**Spec:** `docs/superpowers/specs/2026-09-06-antigravity-continuity-design.md`

## Tasks

- [x] **Task 0** Research: binary strings, embedded hook docs, proto
      descriptors, live hook probes, `/compact` headless probe, context
      windows (see spec §2).
- [x] **Task 1** `agentic_rag/transcript_agy.py` + agy support in
      `transcript.build_digest`, `mining_window.read_window`,
      `capture._transcript_state` (`tests/test_transcript_agy.py`).
- [x] **Task 2** `integrations/agy/hooks.py` owned hook + lossless merge
      (`tests/test_agy_hooks.py`).
- [x] **Task 3** `integrations/agy/install.py` check/backup/publish/restore
      (`tests/test_agy_install.py`); `install.py` `--agy` target and
      target-aware rollback records; `cli.py` flags and output
      (`tests/test_install.py`, `tests/test_cli.py`).
- [x] **Task 4** `hooks/agy.py` dispatcher; `prompt_recall.recall_context`
      (`tests/test_hook_agy.py`).
- [x] **Task 5** `assets/agy/compact_prompt.md`, `integrations/agy/prompt.py`,
      wheel/sdist force-include, version 0.5.0.
- [x] **Task 6** Docs: what's new 0.5, handbook chapters 03/05/06/07/10/11,
      README, CHANGELOG, FEATURES, BACKLOG, doc contract test.
- [ ] **Task 7** Live rollout on the maintainer machine: `rag install --agy
      --check`, `rag install --agy`, new `agy` conversation in a trusted
      workspace, `/hooks`, manual `/compact`, `rag status`; record in
      BACKLOG 0.4.
- [ ] **Task 8** Observe one automatic compaction; confirm or correct the
      marker detector.
