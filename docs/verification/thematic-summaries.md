# Feature7 / PB-5.7 verification and review evidence

## Scope

- Requirement: [Issue32](https://github.com/phense/agentic-rag/issues/32), [RAG-5.7 AC-001–007](../specs/RAG-5.7-thematic-summaries/spec.md).
- Supported source: `bd01d97b1188e6bb0cf71e838c7c35e3449d8f3b`, package0.5.0, schema001–016.
- Candidate: `feature/thematic-summaries`, ignored isolated worktree; exact measured bytes in [results.json](../benchmarks/2026-10-03-thematic-summaries/results.json).
- Procedure: [PB-5.7](../playbooks/thematic-summaries.md), operator/maintainer, source016→017 and local refresh/recovery.
- Validation: full Python/Node suites, actual old/new/rollback CLI/MCP, public synthetic fault/quality fixtures and strict private production-snapshot recovery.
- State tooling: no repository `.engineering-method` tree or local `scripts/project-state`. Git, canonical Issue32 and spec/plan/tasks maintain continuity; no competing ledger, installed-wrapper mutation or successful event-ledger recovery is claimed.

## Fresh verification

Commands run from the candidate root with the canonical interpreter:

```sh
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_thematic_summaries.py --repeats 20 --trading \
  --private-recovery-dump /private/operator-selected/source016.dump \
  --private-recovery-report /private/operator-selected/backup-report.json \
  --output /private/operator-selected/thematic-results.json
```

Observed final result: **1076 Python tests passed in146.91s;7 Node tests passed
in66.061ms**. Baseline was1039 Python tests in139.13s and7 Node tests. The37 new
thematic cases cover consumer-visible behavior, real database transactions and
wire types. The existing009→current migration test was updated to expect017:
the first full run had1069 passing/one stale-list failure, followed by a passing
targeted regression and this fresh full1076 result. No concurrent pytest suites
shared the test database. Measurements own random disposable databases.

Tests cover exact cited substrings, known/global/foreign/unknown scopes, domain
selection, source withdrawal/review changes, omitted supporting-source versions,
replacement/history/expiry/future evidence, malformed selectors, MCP coercion,
reader authority, idempotent refresh, audit rollback/interruption, concurrent
readers/writers and source withdrawal during hydration. Missing017 and failed SQL
leave the baseline transaction usable. Existing profile/hook/pin/checkpoint tests
retain their contracts and caps. Timeout-setting tests preserve shorter caller
limits; the code restores settings on successful reads and savepoint rollback.

## Independent implementation reviews

Independent reviewer `/root/review_thematic_design` did not implement the diff.
It inspected the complete production/migration/test/measurement-driver change
against source `bd01d97` and Issue32. Design review preceded the full reviews;
all reviews were read-only static inspection without database/provider execution.
Coordinator execution establishes the test/rehearsal results separately.

| ID | Severity | Finding | Verified resolution |
| --- | --- | --- | --- |
| R7-01 | Medium | Idle connection `commit=False` could be committed by a top-level transaction helper. | Fresh-connection rollback regression observed red, then fixed by explicit caller transaction ownership and autocommit rejection; cache/audit both roll back. |
| R7-02 | Medium | Context discarded theme partial/failure warnings and silently selected two entries. | Omission regression observed red, then fixed by theme-scoped warning propagation and explicit two-entry cap notice. |
| R7-03 | Medium / Important | Procedure did not give executable guarded code rollback. | Added exact clean-check/worker-lock/detached-source/revision/client verification branch; executed verbatim on owned Git/DB/lock fixtures. |
| R7-04 | Low / Minor | Current CLI/MCP reference retained historical8/14 tool count. | Corrected current9/15 versus historical adopted8/14, preserving six writes. No Low bug deferred. |

The subsequent complete implementation/driver review found no unresolved
Critical, High, Medium or Low bug. The private-recovery extension was separately
reviewed with the same clean verdict. It validates checksum before strict restore,
uses marker-owned targets, preserves original state, writes only through gateways
on the copy and publishes aggregates. Final complete bounded review including both
drivers, all tests and documents returned **Ready, no unresolved Critical, High,
Medium or Low findings**. Final documentation review is recorded below.

## Rehearsal

- Status: passed for the recorded isolated branches; last validated2026-10-04 local session.
- Validating party: coordinator execution; independent reviewer inspected code/evidence rather than re-executing it.
- Authority: maintainer-requested isolated compatibility/recovery tests; canonical Trading reader controls only.
- Public installation: source016, seven domains, multiple scoped projects and gateway actors, qualified claims, global control, pin, checkpoint, queue and audit history.
- Success/retry:017 only, original16 application-table fingerprints and grants preserved; interrupted DDL rolled back; migration retry no-op; actual old/new/rollback search citation parity and MCP8/14→9/15→8/14.
- Strict backups: source016 and candidate017 restored with consistent exported snapshot, --single-transaction and --exit-on-error; every public table and application-role grant matches.
- Private recovered installation: SHA-verified existing source016 dump,17 public-table fingerprints match its private inventory; all15 protected tables retain original rows across migration and summary generation. This includes10466 documents,571 assertions,12666 edges,995 accepted batches,1400 queue rows,25 checkpoints and22 pins;37147 historical audit IDs retained. Original grants preserved and owned copy cleanup verified.
- Practical cost/coverage: three original-corpus and three public synthetic paired cases,20 warm comparisons per route, first calls separately recorded, all citation/filter checks pass. Creation is one observation per case, unchanged refresh20 observations. One-source synthetic corrections rebuild1/reuse7. [Detailed numbers and denominators](../benchmarks/2026-10-03-thematic-summaries/README.md).
- Code activation/recovery: `scripts/verify_thematic_activation.py` executes the exact PB migration/fast-forward and rollback Python snippets on an owned clone, populated017 database and injected private worker-lock path. Busy lock stops without changes; detached rollback preserves prior branch tip, protected rows and017, real source/candidate/rollback CLI citations match, lock reacquisition and resource cleanup pass. [Raw activation evidence](../benchmarks/2026-10-03-thematic-summaries/activation-results.json).
- Untested/limited: no live017 adoption, no already-running end-device reconnect, no human semantic relevance/answer-quality score, no true cold-cache measurement, no arbitrary external ACL or other source-version guarantee. Private deployment measurement uses current references; historical evolution and invalidation have separate temporal tests. Operator activation uses the final approved production target; isolated Git snippets use a disposable candidate fixture commit with the same seven production files. Backup and MCP evidence come from the summaries driver; the activation driver verifies Git/lock/CLI plumbing only.

## PB-5.7 content review

Draft includes exact current interfaces, source/target/schema boundaries, strict
backup verification, worker-lock behavior, transactional migration/retry,
activation, baseline fallback, code-only rollback and explicit authority boundaries.
Independent reviewer `/root/review_thematic_design` returned **Ready** on2026-10-04
after complete document/procedure inspection. Reviewed and rehearsed PB SHA-256:
`c09c53762b5b68e5baefc4ee2bc094c78c11b9c70092a7a6ba3749348cdef49f`.
R7-03/R7-04 are resolved. The coordinator applied Humanizer/reference/procedure
checks while authoring and verified local links. Content review is static;
execution is the separate two-driver rehearsal above. No review or fixture
timestamp authorizes production activity.

## Production boundary

Canonical checkout remains at `bd01d97`, schema016, source MCP8 reader/14 total
tools. Preflight verified7 domains,22 pins,25 checkpoints and the configured
Codex gpt-6.1-sol/high provider; no provider run was needed. Client settings and
editable installation were read only. No production migration, configuration
change, knowledge/cache write or service interruption was invoked. Source016
has no theme cache, so canonical Trading's three reader controls correctly report
unavailable with baseline retained,0 writes and0 providers. Private recovery uses
a prior verified snapshot, not a freeze of the concurrently changing live store.

Feature6's historical local index has been reconciled to its authorized PR44
merge/adoption at `bd01d97`, schema016:1039 Python/7 Node checks,12 protected
tables,37147 historical audits and checkpoint/queue/batch IDs preserved,
strict17-table restore and fresh8/14-tool clients. Evidence is the private
research-rollout report and [canonical adoption comment](https://github.com/phense/agentic-rag/issues/31#issuecomment-5973683496).

## Acceptance and next action

Code, isolated execution and independent final reviews are complete. Publish/link
the bounded PR and request approval of that specific PR. Do not merge or deploy on silence. Issue32 remains open until applicable
merge and separately authorized production rollout evidence are recorded.
