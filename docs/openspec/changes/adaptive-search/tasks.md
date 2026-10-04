# Change Tasks: Adaptive retrieval fast paths

## Stable work ID

- Backlog ID: 5.1; Issue: #26
- Change ID: adaptive-search
- Proposal: docs/openspec/changes/adaptive-search/proposal.md

## Tests

- [x] C001 Write and observe meaningful red routing, eligibility, fallback and strategy tests.

## Implementation

- [x] C002 Implement bounded shared routing and additive CLI/MCP controls; depends on C001.
- [x] C003 Verify all current suites and old-call/source contracts; depends on C002.
- [x] C004 Measure three practical paired Trading scenarios and synthetic fault boundaries; depends on C002.
- [x] C005 Independently review complete diff, fix all Critical/High/Medium bugs and re-review.
- [x] C006 Publish numerical evidence, compatibility and rollback guide, update capability state and submit PR.
- [x] C007 Obtain explicit merge approval, then verify merged source and separately report deployment state.

## Dependencies

Tasks are sequential; read-only review may inspect evidence while the coordinator prepares documentation.

## Completion evidence

825 Python tests passed in 31.40 s; 7 Node tests passed. See
docs/benchmarks/2026-10-03-adaptive-search/README.md and trading-reader.json for
source hashes, reader-only paired timings, quality denominators and populated rollback checks.
Before the separately authorized adoption recorded below, no production code,
schema, configuration or knowledge mutation had been performed.
Independent final review: Critical 0, High 0, Medium 0, Low 0; see review.md.
PR #36 created and linked to the T3 thread. Both GitHub offline benchmark CI runs pass.
Existing AnyIO/PyJWT dependency alerts are tracked in Issue #37, outside this change review.
Explicit maintainer approval received; PR #36 merged as`f27acd9`. Production checkout
adopted the three approved feature PRs at`ae4a102` on 2026-10-03.

- [x] All implementation and acceptance behavior is complete with current evidence.
- [x] Accepted requirements are ready to synchronize before archival.

## Playbook obligations

No new operational playbook or migration is required by this read-only code delta.

## Local adoption — 2026-10-03

Separately authorized production rollout: consistent backup restored into an owned
scratch database, all16 production table fingerprints unchanged,930 Python/7 Node
tests and fresh read-only/authorized MCP clients verified. Existing MCP processes
can coexist until reconnect. See [rollout evidence](../../../verification/three-feature-production-adoption.md).
