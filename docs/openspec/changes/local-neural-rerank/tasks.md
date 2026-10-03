# Tasks: Local neural reranking

- [x] R001 Verify real trained model, pinned resource identity and synthetic smoke.
- [x] R002 Observe red then green for automatic eligible ordering with original evidence.
- [x] R003 Verify policy bypasses, malformed scores/models, timeout/pressure/fork,
      scope/domain/role/source/time boundaries, CLI/MCP and payload preservation.
- [x] R004 Rehearse populated old/new concurrent readers, endpoint failure/restart,
      code rollback and unchanged database state; run full Python/Node suites.
- [x] R005 Publish three attributable paired practical examples and warm/cold/resource limits.
- [x] R006 Independent complete review and fixes until no Critical/High/Medium.
- [x] R007 Create/link feature PR, obtain specific approval, merge and record separately authorized local adoption.

Verified red→green ordering and baseline-attribution tests. Final Python930 passed
in35.87s; Node7 passed. Three actual previous-revision Trading comparisons have
20 paired calls per case with unchanged query/context/eligibility boundaries.
All five candidate runtime hashes match the measured files; baseline source hash
matches git342bccf. Actual old/new populated coexistence/outage/retry/rollback
preserves every row in17 public tables. Two process-cold synthetic model starts
and40 warm smoke calls discriminate positive/negative evidence. Final independent review: Ready, zero unresolved findings.

PR #39 merged with explicit approval as`ae4a102`. The maintainer separately
authorized local adoption of PRs #36/#38/#39, completed on 2026-10-03. Continue
feature5.4 / Issue #29 after the production-adoption documentation handoff.

## Local adoption — 2026-10-03

Separately authorized production rollout: consistent backup restored into an owned
scratch database, all16 production table fingerprints unchanged,930 Python/7 Node
tests and fresh read-only/authorized MCP clients verified. Existing MCP processes
can coexist until reconnect. See [rollout evidence](../../../verification/three-feature-production-adoption.md).
