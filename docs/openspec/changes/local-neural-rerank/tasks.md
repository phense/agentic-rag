# Tasks: Local neural reranking

- [x] R001 Verify real trained model, pinned resource identity and synthetic smoke.
- [x] R002 Observe red then green for automatic eligible ordering with original evidence.
- [x] R003 Verify policy bypasses, malformed scores/models, timeout/pressure/fork,
      scope/domain/role/source/time boundaries, CLI/MCP and payload preservation.
- [x] R004 Rehearse populated old/new concurrent readers, endpoint failure/restart,
      code rollback and unchanged database state; run full Python/Node suites.
- [x] R005 Publish three attributable paired practical examples and warm/cold/resource limits.
- [x] R006 Independent complete review and fixes until no Critical/High/Medium.
- [ ] R007 Create/link feature PR; ask specific approval before merge. Live adoption remains open.

Verified red→green ordering and baseline-attribution tests. Final Python930 passed
in35.87s; Node7 passed. Three actual previous-revision Trading comparisons have
20 paired calls per case with unchanged query/context/eligibility boundaries.
All five candidate runtime hashes match the measured files; baseline source hash
matches git342bccf. Actual old/new populated coexistence/outage/retry/rollback
preserves every row in17 public tables. Two process-cold synthetic model starts
and40 warm smoke calls discriminate positive/negative evidence. Final independent review: Ready, zero unresolved findings.

PR #39 submitted and linked to the T3 thread. Specific merge approval remains
pending; it will cover the merge only. Continue feature5.4 / Issue #29 afterward.
Production adoption remains separately authorized and tracked in Issue #28.
