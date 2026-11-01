# PB-067-OPS review and rehearsal evidence

Playbook: [rag-067-extraction-policy.md](rag-067-extraction-policy.md).
State: **drafted and rehearsed by the implementer; independent content review
pending (S2).** Live rollout is separate and not authorized by this record.

## Rehearsal

All rehearsals ran on owned, automatically dropped PostgreSQL 17.10 databases on
a local test server (port 55460), never on a live store. Providers were mocked:
`llm.run_structured` raised on any unplanned call; the planned mining steps used
a deterministic mock provider.

| Part | Rehearsed by | What ran |
|---|---|---|
| A1–A6, A8, B1 (PYFRESH, PYGATE, PB067-CLIENTS), B2–B5, C1 (hook path and central `/v1/windows`), C2, C3, integrity check, D prospective rollback, D post-upgrade backup and restore, interrupted-upgrade markers | `tests/service/test_extraction_policy_playbook.py` | The playbook's `rag service` and `rag extraction` commands through the real CLI on a store populated by the archived 0.6.19 code (`01bc13b`); its `PYFRESH`, `PYGATE`, `PB067-CLIENTS` and `PB067-INTEGRITY` blocks; `mv` activation and recovery; REST admission refused with 503 while the file was invalid and accepted after recovery; a provider outage, a file replacement and the retry under the admitted digest; a post-upgrade verified backup restored into an empty owned database |
| A4 interruption, old pending and accepted work, D code-only return (0.6.19 reads and writes on schema032), the 0.6.19 miner bypass behind B1, pre-upgrade restore limit | `tests/service/test_extraction_policy_upgrade.py` | Interrupted migration and retry, preservation checks, actual 0.6.19 reads/writes before and after bindings exist, 0.6.19 mining of a job admitted with a custom policy, restore of a backup with bindings, pre-upgrade restore |

Observed on 2026-11-01 at `048a9f8` (playbook file passed alone, then in the
serial affected run recorded in [V-067](../../verification/issue67-extraction-policy.md)):

- A: inventory `supported: true`; preflight `ready: true`; upgrade applied
  `032_extraction_policy.sql` with `restore_verified` and
  `original_rows_unchanged` and wrote `policy032.dump.manifest.json`; the retry
  applied nothing; `status` succeeded; the label `0.6.20` exited 1. The integrity
  check returned 0 in every column.
- B1: `PYFRESH` printed `0.6.20` and the installed `METADATA` path. `PYGATE`
  exited 1 and named a process started before the installation marker; after a
  restart it printed `no_stale_processes`, exit 0. `PB067-CLIENTS` returned the
  expected columns.
- B2–B5: `validate --file` printed `valid: true` and an `xf1:` identity;
  `inspect` listed `builtin, global, domain:programming` for programming in
  team-a; `dry-run` reported 0 provider calls and 0 writes; after `mv` the
  configured `validate` showed the same identity.
- C1: with the malformed file `validate` exited 1; the hook-path admission raised
  `invalid extraction policy: reserved_setting at rules[1].write_domains` and
  added no queue row; `/v1/windows` answered 503 `extraction_policy_invalid`;
  after `mv POLICY.prev POLICY` the same window was accepted (202) and the hook
  admitted its job.
- C2/C3: `inspect --queued` showed an `xb1:` digest for the new job and the
  window and `legacy-builtin` for the job admitted by 0.6.19; after the outage
  the job showed `bound` equal to its admitted digest; with file B in place the
  retry made the second provider call, kept the admitted digest and dropped the
  lesson and signal the admitted policy disables.
- D: after a prospective rollback to A, a new admission carried A's digest and
  the accepted batch still named the retry digest; the post-upgrade backup was
  restore-verified and the restored store had identical integrity counts and the
  immutability trigger.

## Not rehearsed

- `rag service job-retry RECEIPT` itself (a client command over HTTP); the
  underlying `retry_receipt` path is exercised by
  `tests/service/test_extraction_policy_central.py`.
- PB-063 R1–R4 commands beyond the `pg_restore` restore of the post-upgrade dump.
- Production, TLS, systemd, macOS and multi-host operation.

## Review

Independent content review: pending (S2 / T067-008). No reviewer verdict is
claimed here.

Known rehearsal fragility: the `PYGATE` comparison has one-second process
start-time resolution. The structurally identical PB-065 gate rehearsal failed
once under load during this slice and passed on immediate rerun
(log preserved by the implementer, not caused by RAG-067).

## Coordinator correction and renewed rehearsal before independent review

The prior048a9f8 procedure labelled a post-upgrade dump0.6.19 because it refused
the actual0.6.20 source. That workaround is withdrawn. The current procedure and
operator code support truthful0.6.20 inventory/backup manifests and refuse the
future0.6.21 label. A new actual verified-backup regression first failed, then
passed with its source-version and binding-row manifest assertions. The changed
PB-067 commands, schema tests and affected lifecycle/synthesis upgrade tests ran
serially:13passed,1known warning,exit0,108.16s (`root-current-backup-green.log`).
The current PB-067 rehearsal exercised the0.6.20-labelled dump/restore. It retains
the central-mining and host limitations above; independent content and integration
acceptance are still pending.

## Independent review and coordinator correction

The independent review at54573e7 rejected M1/PB-I1: a new local job could use an
older failed job's binding, even after changing projects. The coordinator chose
conflict refusal, preserving the immutable binding. C2 and Completion now require
matching admitted/bound policies and explain the stop/escalate decision. Four
regressions first failed; after correction35 affected checks passed (one known
Starlette warning, exit0,30.62s). These include queue conflict recovery by a new
ordinary admission under the original policy/project, central retry/scope and
the populated PB-066 upgrade/restore rehearsal. Independent correction acceptance
and the final full suite remain pending; the earlier full2 was interrupted and
is not a pass. Minor process-gate and regular-file assumptions are now explicit.
The integrity check still cannot detect an old miner's policy bypass; the
all-miner gate is mandatory and that diagnostic limit is tracked in Issue75.

The changed PB-067 commands and documentation continuity check were also
rehearsed after the correction:18passed,1known warning,exit0,15.92s
(root-review-pb-docs-green.log). Nonblocking findings LOW-050..055 are tracked in
[Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6553145423).

## Domain-set correction (CM1 / PB-CI1)

The independent correction review rejected624dce6: full-bundle comparison could
strand builtin retries after domain additions or permission revocations, and
unchanged-file recovery after adding a domain. The comparison now checks
common-domain and domainless effective policy hashes; legacy retries require a
builtin binding. Project checks, immutable binding and current-authority
intersection remain. Newly available domains are not added to an existing
binding. C2 distinguishes compatible domain-set changes from rule conflicts.

Focused regressions reproduced three failures (local builtin retry, unchanged
file recovery, central builtin retry) and one passing captured-policy control.
After correction41affected tests passed,1known warning,exit0,19.61s. Three
additional negative cases protect real common-domain rule changes, domainless
rule changes and custom-to-builtin conflicts. The test harness initially reused
a module-scoped central session and then duplicated earlier fixture content;
unique session/source text corrected those test-only assumptions. Original
failed logs are retained, not counted as product evidence. Full3 was interrupted
on unchanged624dce6 for this repair and is not a pass. Independent focused
acceptance and final full-suite verification remain pending.

### Post-CM1 evidence at e88717f

- Actual PB-067 populated upgrade/restore plus upgrade preservation and docs
  continuity:19passed,1known warning,exit0,36.88s.
- Coordinator rerun of the unchanged prior independent correction script:
  37/37 checks passed,0errors; own databases cleaned. This reuses the probe
  design but is not an independent review. Its prior failed artifact is retained.
- Frozen EN/DE measurement:3repetitions,all labels matched,identical deterministic
  outcomes; new raw observations in results-final.json preserve the first run.
- Node adapter:7/7,exit0. Offline lock check:55packages,exit0.
- Built wheel:191entries,186source payloads byte-identical,32SQL migrations.
  SHA256953cf5f60c3e3716690cde5dea2271590abbc54af71684c44512c47d57c26814.
  Import from the extracted wheel on a new owned database passed schema
  validation and durable binding; the database was dropped after the smoke test.

No full-suite pass or independent acceptance is inferred from these checks.
