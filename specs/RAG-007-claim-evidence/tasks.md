# Tasks: RAG-007 claim evidence

Base c81aec2; serialized ownership, no concurrent database tests.

### Slice S1: Evidence and lifecycle foundation

- [x] T001 Test then implement migration012, evidence.py and store gateway wrappers:
  claim/source/span identities, bounded attachments, exact reuse, source lifecycle,
  explicit review, audit/transaction semantics. AC002/003/004/007, IC002/004,
  AF010/011. No dependencies.
- [x] T002 Extend mining source grounding and accepted batches, immutable managed
  claims, temporal source attachment and curation exclusion. Test user/proposal/
  hypothetical/inference/correction, redaction and legacy batch handling.
  AC001/002/006/007, IC001, AF010/013. Depends T001.

### Slice S2: Retrieval and verification

- [x] T003 Compose source eligibility with temporal SQL, compact search/get/review
  metadata, CLI/MCP source/review interfaces and hook labels. Test pre-limit/hops,
  surviving evidence, historical access, reader privileges and incomplete legacy.
  AC004/005/006, IC003/004, AF012. Depends T001/T002.
- [x] T004 Independent complete-diff review, as-built reconciliation and derived
  source->reader plus failure/replay integration tests; synthetic semantic evaluation,
  full suite/build/migration verification, docs/FEATURES/BACKLOG.
  All AC/IC/AF. Depends T001–T003.
- [x] T005 Fresh backup, worker-lock migration/code activation, unchanged legacy/pin
  readback, publish/CI and issue completion with explicit rollout approval as required.
  Compatibility/operational gate. Depends T004.
