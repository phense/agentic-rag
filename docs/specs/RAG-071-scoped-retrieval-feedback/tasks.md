# Tasks: RAG-071 scoped retrieval feedback

## Ownership and integration

One implementation writer owns runtime/SQL/tests/user documentation/release
metadata. The coordinator owns spec/plan/tasks/UML, continuity and final
acceptance. No parallel writers. Source9ee02b7, runtime0.6.27/schema036;
release0.6.28/schema037. Independent review covers the complete implementation
range; a passing report is not substituted for actual integration checks.

### Slice S071-1: Audited scoped capture and signal contracts

- [x] T071-001: Freeze meaningful red tests for explicit event capture, no raw
  query retention, same-key replay/conflict, own-scope access, two actors/clients,
  stale revisions, retraction, rate/storage limits and audit rollback.
  AC-001..006; AF071-001..004.
- [x] T071-002: Add migration037, expected grants/RLS/identity guards and schema
  validation; implement `feedback.py` gateway and disabled-by-default config.
  Retain namespace accounting independently of scoped content visibility; test
  quota enforcement after domain/project grants are revoked.
  Preserve001..036, search behavior and all knowledge hashes. Depends:T071-001.
- [x] T071-003: Add MCP write tools for search/submit/update/retract and read
  tools for own get/list; reuse existing authenticated REST tool route. Add CLI
  `feedback` adapter including remote mode via RemoteClient. Deny readonly/foreign
  actors uniformly and recheck current authority at commit. AC-003/009, IC-001..003.
- [x] T071-004: Run real-PostgreSQL, real HTTP/CLI/MCP targeted tests and relevant
  existing scope/engine/request/client tests. Freeze input hashes/results; fix
  only confirmed failures. Depends:T071-002/003.

S071-1 integration evidence: `59c647b` tests first, `4cc570f` implementation;
74 targeted tests passed in92.76s, exit0,418 input hashes unchanged,001..036
byte-identical. Complete independent review remains T071-010.

### Slice S071-2: Private evaluation and compatibility

- [ ] T071-005: Red tests then local-only operator approval/summary/private export,
  independent actor/source grouping, query hash/secret screening, source/claim
  change and withdrawal, and held-out family separation. AC-005..007, AF071-005.
- [ ] T071-006: Add separate feedback export/evaluation format dispatched through
  the existing private correction evaluator. Reuse private file/hash guards,
  network-free lexical search and explicit stale denominators. Preserve old
  correction format, public corpora and ranking/truth state. Depends:T071-005.
- [ ] T071-007: Prepare the T071-009 release-label component first, then
  populated archived0.6.27 source with vectors/scopes/pin/queued job:
  interrupt037, retry, source/target independent restore, old reader and rollback
  with retained metadata. Compare original rows/ACL/owners/sequences. AC-008;
  AF071-006. No production mutation in tests.

### Slice S071-3: Operations, release and independent acceptance

- [ ] T071-008: PB07101 `docs/retrieval-feedback.md` with opt-in, local/remote
  capture/update/retract, operator approval/private export/evaluate, caps,
  changed/withdrawn sources and executable upgrade/recovery. Use authoring/review
  skills; record a real command rehearsal and two or three measured examples.
- [ ] T071-009: Finalize exactly0.6.28 in project/lock/badge/changelog and supported
  labels (release-label component before T071-007), preserve historical references,
  update future-refusal tests, README,
  FEATURES and config reference. Lock/wheel and Node checks as applicable.
- [ ] T071-010: Coordinator reconciles as-built architecture and derived success/
  recovery probes, obtains independent complete bounded review, resolves C/H/M
  and Important playbook findings and tracks Low issues separately.
- [ ] T071-011: Final relevant tests and one full suite before PR on unchanged
  runtime inputs. Record terminal exit/results; no running-log pass claim.
- [ ] T071-012: Create focused PR, respect CI and review gates, merge and deploy
  under current autonomy only after verified populated upgrade/restore; preserve
  rollback evidence and report actual runtime behavior on both hosts.
