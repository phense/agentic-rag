# PB07101: Review and rehearsal evidence

## Scope and identity

- Playbook: [PB07101](../retrieval-feedback.md), target0.6.28/schema037.
- Requirements: [Issue71](https://github.com/phense/agentic-rag/issues/71),
  AC-001–009 and T071-008/010.
- Source: deployed0.6.27, commit289b8bc/schema036. Core4cc570f,
  private evaluation and release3ad0f2a. Migration001–036 remain byte-identical.
- Owner: repository maintainer; readiness required before enablement.

## Practical examples

A fresh owned PostgreSQL database held three synthetic original-backed memories.
The coordinator invoked the actual CLI in14 subprocesses on3ad0f2a. All14 exited0;
whole rehearsal29.597s. Input hashes were captured before execution and unchanged
after it. Times below include CLI startup and are not service-load measurements.

| Example | Before | Observed result | Wall time |
|---|---|---|---:|
| Useful result, lost-response replay, edit and retract | No event or signal | One event and one signal; repeated submission has the same ID; revisions1→2→3 end retracted | 10.325s |
| Wrong source | One returned memory, expected memory absent | One explicit negative signal approved; private evaluation reproduces the miss | 6.711s to approve |
| Missing evidence | No search results | Expected source remains eligible, explicit negative signal approved; private evaluation reproduces the miss | 4.470s to approve |

Export selected3 negative records, exported2 and withheld1 retracted record.
Evaluation counted2 baseline misses and2 reproduced current misses; stale0,
withheld1. It changed no application data and invoked no provider. Both exported
CLI cases happened to fall in development; they do not establish a held-out
comparison. A separate six-case integration test covers3 development and3 test
source families, all6 explicit misses reproduced. Neither run claims improved
retrieval quality, training or automatic policy activation.

All50 original public tables (excluding the audit log and new feedback tables)
retained identical row hashes. The export/report files were0600 under a0700
parent outside Git. Raw queries did not enter event JSON. The owned database was
removed. [Sanitized numerical record](../benchmarks/2026-11-03-retrieval-feedback/results.json).
Private queries, exports and complete result bodies are not published.

## Contract and upgrade checks

- S071-1:74 targeted tests passed in92.76s, exit0;418 frozen inputs unchanged.
  Real PostgreSQL, authenticated REST/MCP and queued RemoteClient/local CLI cover
  own/foreign/anonymous/readonly callers, replay/revision races, source changes,
  legacy text, expiry, quotas after scope revocation, audit rollback and commit
  authority. These use synthetic data and do not establish production load.
- S071-2:33 targeted tests passed in62.57s, exit0;388 runtime/test/release inputs
  unchanged. Private paths/hash tampering, old correction compatibility,
  source-family separation, user independence, approval invalidation and disabled
  approval behavior are covered. Initial test-first evidence hashes only its test
  file; a separate disabled-approval red bound both relevant inputs.
- The populated upgrade imported archived289b8bc, confirmed027/schema036, seeded
  two users/domains/projects, vectors, a pin, a legacy memory and a pending job.
  Process exit9 after037 DDL before commit left all source rows unchanged. Retry
  applied only037; another retry applied nothing.
- Independent source and target dump/restores preserved75 original rows in50
  tables, ACLs, owners, sequences, vectors, pins and the pending job. The restored
  target has54 tables and identical `fb1:` versions. Old027 scoped readers still
  return exactly one expected source per user. Retained037 code rollback keeps
  rows; the old schema-aware operator refuses `unsupported_source_schema`.
- Three machines belonging to two service users give3 raw signals but2 independent
  signals in one source family. Counts never alter ranking or claim review.

## Content review and remaining gates

The coordinator followed the standalone medium documentation-authoring and
playbook-authoring workflows, compared CLI/MCP forms with source, checked local
link targets and rehearsed writer/private-operator commands. The populated
upgrade/recovery steps are exercised by the real operator integration above;
no production maintenance procedure was run for this feature.

Release checks pass: consistent028 project/lock/badge/changelog, offline lock
validation,17 documentation tests,7 Node tests and wheel build. All37 SQL files
and three new feedback modules in the wheel match source bytes.

Independent whole-feature code/playbook review and the single pre-PR full suite
remain pending. Runtime delivery and production
feedback enablement are separate; neither has occurred for0.6.28.
