# Feature6 / PB-5.6 verification and review evidence

## Scope

- Requirement: [Issue31](https://github.com/phense/agentic-rag/issues/31), [RAG-5.6 spec](../specs/RAG-5.6-bounded-research/spec.md), AC-001–007 and PB-5.6.
- Source: `19ed09c1b3c46d907254f63a1370586ea3213966`, schema001–016.
- Candidate implementation: `22873ccb8bdfdb1a0050bd4fd2f998772be77b16` on `feature/bounded-research`, [PR44](https://github.com/phense/agentic-rag/pull/44); measured implementation/driver hashes in [results](../benchmarks/2026-10-03-bounded-research/results.json), checked unchanged at end of measurement and against committed bytes.
- Procedure: [PB-5.6](../bounded-research.md), system operation and code-only upgrade/recovery.
- Owner: maintainer; delivery readiness before PR merge, rollout readiness before separately authorized adoption.
- Validation level: complete suites, real CLI/stdin MCP/worker processes, populated isolated old/new/rollback and strict restore; canonical Trading reader aggregates only.

## Fresh verification

Commands run from the candidate checkout using canonical Python3.13:

```sh
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/bounded-research \
  /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/bounded-research \
  /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_bounded_research.py --repeats 20 --trading --provider-smoke \
  --output docs/benchmarks/2026-10-03-bounded-research/results.json
```

Observed on2026-10-03: **1039 Python tests passed in135.62s;7 Node tests passed
in74.919ms**. Baseline was987 Python tests in138.35s and7 Node tests.
There are52 new targeted cases; the targeted run passed in5.42s before the
final full run. The isolated measurement command exits0 and records three
paired scenarios, populated compatibility and strict restore all passing.
The earlier full runs1017 and1031 passed but are superseded by this final
1039 result. No simultaneous pytest suites shared the test database during
final verification; measurement owns a separate random database.

Test-first failures were observed for the initially missing capability and
later review regressions before their implementation fixes. Budget/type,
source-trust/duplicate/fabrication, relevant late graph chunks, domain/project/
active/temporal boundaries, provider fail-closed privacy, concurrent readers,
deadlines, cancellation and retry have output-level checks. Expired-edge
tests use a read-only SQL projection because the public gateway offers no
edge-expiry edit; they do not hand-write fixture knowledge or audit rows.

## Independent implementation review

Reviewer `/root/review_research_design` was independent of implementation,
read-only, and reviewed the complete bounded implementation, CLI/MCP, tests
and measurement-driver changes against source19ed09c. Design review and
successive implementation reviews verified each correction. Final review
verdict: **no remaining Critical, High or Medium findings**. No Low finding
was deferred. The reviewer ran inspection/diff checks and a focused synthetic
plan-failure reproduction; it made no database or provider calls.

| Finding | Severity | Correction and verification |
|---|---|---|
| R6-01 inherited Claude tools/MCP | High | Research-only runner disables tools, settings/hooks, MCP, skills and persistence; argv regression. |
| R6-02 source quorum applied too coarsely | Medium | Source spans qualify each exact statement; unrelated document roots cannot count. |
| R6-03 parent scope resolution outside deadline | High | Filesystem/Git resolution moved into worker; responsive deadline regression. |
| R6-04 Codex read/web/delegation tools | High | Research-only feature/tool overrides, empty MCP, ignored user config/rules, private cwd; actual configured-provider probe succeeds. |
| R6-05 nested provider temporary evidence survives kill | High | Parent-owned TMPDIR/TMP/TEMP; interrupted nested-temp regression. |
| R6-06 graph prefix and cumulative chunk bound | Medium | Rank full document before shared64-candidate limit; late-chunk regression. |
| R6-07 MCP type coercion | Medium | Strict booleans/numeric types; eight invalid wire cases. |
| R6-08 provider planning failure later hidden | Medium | Failure latches local mode/abstention; red-before-fix regression independently checked. |
| R6-09 measurement provider accounting/provenance | Medium | Separate local/live counts, per-operation counters and frozen before/after code+driver hashes. |
| R6-10 new temporal/active graph paths lack direct tests | Medium | Seven historical/expired/future/archived/domain cases with positive controls and no swallowed-error passes. |

## Content review

Independent reviewer `/root/review_research_design` returned **Ready** after
inspection of the completed document set. The
[separate content review](bounded-research-content-review.md) records the
exact PB SHA-256, method, corrected candidate-directory selection and limits.
It distinguishes the recorded passed rehearsal from independent execution.
No open Critical/Important/High/Medium or deferred Minor/Low findings remain.

## Rehearsal

- Status: **passed** for the required isolated success/recovery branches.
- Last validated:2026-10-03, frozen implementation hashes in results.
- Validating party: implementation coordinator, with independent test/diff review.
- Environment: random owned schema016 PostgreSQL copy, multiple domains/projects, reviewed evidence, pin, checkpoint, jobs and audit history.
- Method/authority: user-authorized isolated acceptance; fixture writes through gateways, destructive restore only into owned disposable databases. Canonical Trading is reader-only.
- Success: actual source/candidate/rollback CLI citations match; MCP7/13→8/14→7/13;16 application-table rows/grants unchanged; schema016 retained;0 application writes during acceptance.
- Recovery: strict consistent-snapshot backup/restore verifies all17 public tables and grants; owned database cleanup passes. Tests verify stalled process-group cleanup, async and actual MCP cancellation, nested temp cleanup and independent retry.
- Untested branches/limits: live Feature6 adoption, already-running end-device reconnect, all possible provider CLI versions, semantic model correctness and stopping remote already-dispatched work. None is represented as passed. No migration or production service interruption occurred.

## Production boundary and freshness

Canonical checkout remains clean at19ed09c and canonical imports still resolve
there. Read-only recheck sees schema016,7 read/13 total tools,7 domains and22
pins. The live document/chunk totals advanced from10448/11838 at preflight to
10466/11856 during this session; active clients/jobs were not stopped, so no
whole-production byte-equality claim is made. Acceptance fingerprints refer
to the isolated installation, not a frozen live store.

Codex and Claude settings hashes remain identical to preflight:
`9e6051f27b4a4307d669345b387e5e681aff295ac24a630d55ecce56ad3fc06c`
and `a388ac8ab7f670416b7deddb6c51b38e12eebc628117342e8aa882d9e2d1de92`.
No installer, production write gateway, migration, configuration edit or
service-stop command was invoked for Feature6. Candidate code was selected
with PYTHONPATH without replacing the canonical editable installation.

State tooling: this legacy index has no `.engineering-method` run tree or
repository-local `project-state`; bundled read-only state-check exited2
because BACKLOG lacks generated task IDs. Git, Issue31 and the linked
spec/plan/tasks retain continuity; no successful event-ledger recovery is
claimed and no competing ledger was introduced.

## Acceptance and next action

Code, independent content review and isolated practical verification are
complete. PR44 is published and linked to Issue31; request
approval for that exact PR. Merge remains pending; production adoption
requires separate authorization and fresh rollout evidence. Issue31 stays
open until its required rollout acceptance is recorded.
