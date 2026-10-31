# PB-065-OPS review and rehearsal evidence

Playbook: [rag-065-pattern-synthesis.md](rag-065-pattern-synthesis.md).
State: **independently accepted at `73ddd02`, with no Important finding open.**
The final review resolved PB065-R07/R08 and independently repeated the hardlink
and backfill-recovery checks. Its one Minor finding, PB065-R09, was then
corrected by the coordinator in C1/C9 and the user guide: a group exceeding the
maximum input cannot be analysed, and the pending backfill holds later requests.
That wording correction was checked against the final probe, without changing
code or executable snippets. Full-suite acceptance remains pending.

## Rehearsal

All rehearsals ran on owned, automatically dropped PostgreSQL 17.10 databases on
a local test server (port 55460), never on a live store. The provider boundary is
the frozen scripted fixture of
[the measurement](../../benchmarks/2026-10-31-pattern-synthesis/README.md); the
outage is a synthetic `LLMUnavailableError`. No real model was called.

| Part | Rehearsed by | What ran | Observed result |
|---|---|---|---|
| A1–A6 | `tests/service/test_synthesis_upgrade.py::test_operator_cli_and_central_service_on_populated_0_6_17` | The exact `rag service` inventory, preflight, plan, upgrade, retry and status commands on a store populated by the archived 0.6.17 code (`81beaf6`) | `030_pattern_synthesis.sql` applied, restore verified, original rows unchanged, retry empty, no synthesis rows (including `synthesis_processed`); label `0.6.18` refused; old 0.6.17 central API served a scoped read before any pattern existed; new API served `memory_pattern_status` |
| A4 interruption, D rollback boundary and restore limits | `tests/service/test_synthesis_upgrade.py::test_populated_0_6_17_upgrade_retry_old_code_recovery_and_restore_limits` | Interrupted migration and retry, old-code reads and writes on schema030 before patterns, accepted-run recovery on a restored copy, disable after a pattern exists with actual 0.6.17 reads, pre-upgrade restore for retained 0.6.17 code | 302 rows in 39 tables preserved; upgrade 1.61 s; after disable, 0.6.18 withheld the pattern while 0.6.17 `get`, `evidence` and `history` served it (`code_only_rollback_after_patterns.verdict = forbidden`); post-upgrade writes absent from the pre-upgrade restore ([evidence](../../benchmarks/2026-10-31-pattern-synthesis/compatibility-evidence.json)) |
| B0, A8, B1–B6, C1, C2, C4 (local and central), C5–C7, integrity check after a disable tick, D post-upgrade restore | `tests/service/test_synthesis_playbook.py` | The playbook's `PYFRESH`, `PYGATE` and `PB065-CLIENTS` blocks and `rag pattern` commands through the real CLI (local, and client mode against the REST API), worker ticks through the central `rag service worker` loop, the `PB065-INTEGRITY` SQL block, and the PB-063 R1/R3 snippets on a schema030 dump | See below |

Observed at product revision `8d9043e` (2026-10-31, serial run of the affected
suites; this file passed, report line `PB065_REHEARSAL`):

- B0: `PYFRESH` printed `0.6.18` and the installed `METADATA` path. `PYGATE`
  exited 1 and named a reader process started before the installation marker;
  after that process was restarted it printed `no_stale_processes`, exit 0.
  `PB065-CLIENTS` returned the expected columns (0 other clients).
- A8: an initialized schema030 store showed no policy and no run.
- B2: `rag pattern enable` with `[synthesis] enabled = false` exited 1.
- B3, B1: enabling printed `pattern policy enabled (v1); forward boundary …`;
  preview printed `(no provider call, no write)` and `sufficient` with zero
  provider calls.
- C2: during the outage the run stayed `pending` after one attempt; after the
  backoff elapsed it became `applied` with exactly one successful call.
- B5, B6: `list` showed `VPN reconnect clears the DNS suffix list [unreviewed, medium]`;
  `show` printed the hypothesis notice, `ev1:`/`src1:` versions and
  `support: 4 independent events in 4 memories`.
- C4 local: after exhausted apply attempts the run was `error`/`apply_failed`/recoverable;
  `rag pattern recover` printed `re-queued (accepted)`; a second recover exited 1;
  the next tick applied it with still one provider call in total.
- C4 central: a writer enabled the I1 scope with the client CLI; after exhausted
  apply attempts in the central worker, client-mode `status` showed the run
  recoverable and its memories `held_for_recovery`; client-mode `rag pattern
  recover` printed `re-queued (accepted)`; the next central tick applied it with
  one provider call in total.
- Integrity check after C4: `patterns` 3, every other column 0. After disabling a
  scope with an open run, `open_runs_of_disabled_policies` was 1; after the next
  tick the run was `withheld policy_disabled` and the check was clean again.
- C1: a window after the forward boundary exited 1; an empty window closed without
  a run; a window below the floor ended `insufficient_independent_support` with
  zero provider calls.
- C6: with the switch off, `backfill` exited 1 and `show` still exited 0.
- C5, C7: `disable` printed `disabled (v2)`; the pattern left `list` and `show`
  exited 1 while the pattern row remained; enabling again made `show` succeed.
- D: `verified-backup --source-version 0.6.17` reported `restore_verified: true`;
  the PB-063 digest and manifest snippets printed `dump_digest_verified` and
  `restore_manifest_verified` on the restored copy, whose integrity result
  matched and whose pattern was readable.
- C3, C8 and C9 recovery semantics (processed membership, held, oversized and
  budget-blocked memories) are exercised by `tests/test_synthesis_forward.py` and
  `tests/test_synthesis_apply.py` through the same scheduler and worker, not
  through the CLI.

The C2/C4 rehearsals simulate two waits with SQL on the owned database: the
provider backoff elapsing (`next_attempt_at`) and the worker's attempts running
out (`status='error'`). Those are the conditions the existing worker reaches on
its own after its configured backoff and attempt limit. The B0 gate rehearsal
uses a temporary installation marker instead of reinstalling the package.

After review at `39b6bd9`, the coordinator changed that marker rehearsal to a
real hardlink from a cache file created before the old reader started. The
original `st_mtime` gate incorrectly printed `no_stale_processes` (regression
exit 1). With `max(st_mtime, st_ctime)`, the same snippet blocked the old reader
and passed after its restart. The complete playbook and local-capture files
then passed together: 8 tests, 1 known upstream warning, 29.77 s, exit 0.
This is a Linux filesystem rehearsal, not a package reinstall or a macOS test.
Step B0 now requires the timestamp check for every installed environment; C8
states the next due policy interval rather than the next worker tick.

## Correction found during rehearsal

The first draft of C1 promised a `backfill` run after every request. An empty
window closes without a run. C1, the contract's as-built notes and the test now
state this.

## Not rehearsed

- Part B with a real model provider, and part D's pre-upgrade restore through the
  literal PB-063 R4 client switch with a 0.6.17 executable (the restore itself and
  old-code reads are rehearsed in the upgrade test). The export of post-backup
  writes in part D is a read-only query, not rehearsed separately.
- B0 on more than one host, on macOS `ps`, or against a real agent session's MCP
  server; B0 cannot detect hosts that are not on the process list.
- A live store, a systemd-managed central worker, or a multi-host deployment.

## Independent review

Original revision: changes required (PB065-R01..R06). Independent S4 review:
those findings resolved; new PB065-R07/R08 required correction. Final review
at `73ddd02`: accepted, with R07/R08 resolved. All 34 fresh integration
assertions passed; four owned databases were removed. B0 was independently
executed against a real hardlink and two environments; the old snippet falsely
passed while the new snippet correctly blocked the stale process. The backfill
waiting/recovery branch was exercised through authenticated REST, the worker and
CLI status. Unchanged success/recovery flows reuse the S4 probes, with the
unchanged-source boundary verified by the 60-file manifest.

PB065-R09's wording correction is coordinator-reviewed against probe F2; it
adds no executable operation. The product limit remains open as
[LOW-044](https://github.com/phense/agentic-rag/issues/75#issuecomment-6548506675).
This content verdict is separate from full-suite and production readiness.

Final full-suite acceptance: `ea6697b`, 1,974 passed/1 skipped/1 known warning,
exit 0, 355 source hashes unchanged. The separate legacy in-place restore correction
was independently reviewed at `c3df902`; coordinator regression corrections
then passed 119 targeted tests and 28/28 restore assertions at `bfeedf0`.
PB-065-OPS executable snippets remain byte-identical to the accepted 73ddd02
version; the verified empty-target service recovery remains unchanged.
