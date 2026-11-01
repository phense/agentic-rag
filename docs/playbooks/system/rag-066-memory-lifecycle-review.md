# PB-066-OPS review and rehearsal evidence

Playbook: [rag-066-memory-lifecycle.md](rag-066-memory-lifecycle.md).
State: **author rehearsal recorded; first independent content review required
changes at `1fc0628`; correction acceptance (T066-011) pending.** The historical
rehearsal below is not a verdict on the corrected playbook.

## Rehearsal

All rehearsals ran on owned, automatically dropped PostgreSQL 17.10 databases on
a local test server (port 55460), never on a live store. No provider was called;
`llm.run_structured` raised on any call.

| Part | Rehearsed by | What ran |
|---|---|---|
| A1–A6, A8, B0, B1–B5, C1–C3, C5–C7, integrity check, D post-upgrade restore, interrupted-upgrade markers | `tests/service/test_lifecycle_playbook.py` | The playbook's `rag service` commands on a store populated by the archived 0.6.18 code (`d4d2372`); its `PYFRESH`, `PYGATE`, `PB066-CLIENTS` and `PB066-INTEGRITY` blocks; `rag review`, `rag lifecycle`, `rag search --view`, `rag get --view` through the real CLI; `memory_lifecycle_preview/apply/correct` over REST as a scoped writer; the PB-063 R2 restore command and R3 `PYVERIFY` snippet on a post-upgrade dump |
| A4 interruption, D code-only return to 0.6.18, old curation fallback, pre-upgrade restore limit | `tests/service/test_lifecycle_upgrade.py` | Interrupted migration and retry, actual 0.6.18 reads and writes before and after decisions, 0.6.18 curation with default budget and with `budget = 0`, restore of a backup with decisions, pre-upgrade restore |

Observed on 2026-11-01: the file passed alone at `baec38f` and in both serial
runs of the affected suites, at `49d37bc` and at `351b6f4` (1,188 passed, exit 0):

- A: inventory `supported: true`; preflight `ready: true`; upgrade applied
  `031_memory_lifecycle.sql` with `restore_verified` and
  `original_rows_unchanged`, wrote `lifecycle031.dump.manifest.json`; the retry
  applied nothing; `status` succeeded; the label `0.6.19` exited 1. The integrity
  check returned 0 in every column.
- B0: `PYFRESH` printed `0.6.19` and the installed `METADATA` path. `PYGATE`
  exited 1 and named a process started before the installation marker; after a
  restart it printed `no_stale_processes`, exit 0. `PB066-CLIENTS` returned the
  expected columns. 0.6.18 curation with `[curation] budget = 0` archived nothing.
- B1–B4: `rag review` printed `duplicate candidates:` and `lifecycle review:`.
  Preview classified the release-checklist copies as `exact_duplicate` with
  `writes: 0` and printed "No write, no provider call."; apply printed
  `decision <id>: exact_duplicate active`; `show` reported `hiding`; current
  search omitted the copy, `include_merged` returned it; `get --view current`
  answered with the kept memory and `resolution: canonical`.
- C: an extension without `--reviewed` exited 1 with `error: review_required`;
  after an ordinary save of the member, `error: stale_version`; different titles
  as exact duplicate `error: proof_failed` (preview code `proof_failed`); a
  project-b copy against a project-a memory `error: scope_mismatch`; the integrity
  counts were unchanged by all refusals. A keyed extension succeeded; the same key
  with another reason exited `error: replay_mismatch`; a decision on the kept
  memory exited `error: chain_conflict`. A contradiction printed `contradiction
  contested` and appeared under `lifecycle review:`.
- C6: `rag lifecycle correct <id> --revision 1` printed `decision <id>:
  exact_duplicate corrected`; current search returned the copy again; `history`
  listed `applied` and `corrected`.
- C7: an ordinary edit of the extension's member made `show` report `stale`, and
  `rag review` listed it.
- B5 central: a writer of `alpha:/projects/a` previewed, applied and corrected a
  decision through `/v1/tools` (HTTP 200 each).
- Integrity after all steps: 4 decisions, every other column 0.
- D: `verified-backup --source-version 0.6.18` reported `restore_verified`; the
  dump restored into an empty owned database with `pg_restore
  --single-transaction --exit-on-error`; the restored inventory passed the PB-063
  `PYVERIFY` comparison (`restore_manifest_verified`); the restored integrity
  result equalled the source's, and the three guard triggers existed. On the
  upgraded store `lifecycle_decisions` and the 031 migration row were both present.

## Not rehearsed

- A3/A7 stopping and starting real services and agent sessions; B0 on more than
  one host. The gate snippets ran against processes of the test host only.
- C4 `busy` and C9 through the CLI: both are covered at the gateway level by
  `tests/test_lifecycle_apply.py` (lock held by another connection, injected
  audit failure), not through the playbook commands.
- C8 `canonical_unavailable` through the CLI: covered by
  `tests/test_lifecycle_views.py` and the measurement (G1).
- PB-063 R4 and the pre-upgrade restore with retained 0.6.18 executables; the
  pre-upgrade restore limit is shown by `test_lifecycle_upgrade.py` on the API.

## Review

The independent content review at `1fc0628` found PB-I1 Important: the integrity
query treated a legal contested relationship as a hiding chain. Its owned-DB
probe passed five of six assertions. Minor findings concerned unaudited-decision
repair, foreign request-key advice and history paging.

`4365348` changes the query to count active hiding decisions only and documents
escalation-only handling of `decision_without_event`. A real gateway fixture
with a contested relationship plus hiding decision failed the old query (two
chains) and passed the corrected query (zero). The same three-test regression
run verifies history paging and detail overflow. `30b4064` scopes request keys
per domain/project and updates C2/C6 advice. The populated rehearsal must run
again for the corrected system; independent content recheck remains pending.
No real service restart, TLS, macOS or multi-host rehearsal is inferred.
