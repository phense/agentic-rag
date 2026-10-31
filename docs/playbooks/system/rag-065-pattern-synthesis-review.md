# PB-065-OPS review and rehearsal evidence

Playbook: [rag-065-pattern-synthesis.md](rag-065-pattern-synthesis.md).
State: **drafted and rehearsed by the implementer; independent review pending**
(RAG-065 S2, T065-009). Delivery stays blocked until that review passes.

## Rehearsal

All rehearsals ran on owned, automatically dropped PostgreSQL 17.10 databases on
a local test server (port 55460), never on a live store. The provider boundary is
the frozen scripted fixture of
[the measurement](../../benchmarks/2026-10-31-pattern-synthesis/README.md); the
outage is a synthetic `LLMUnavailableError`. No real model was called.

| Part | Rehearsed by | What ran | Observed result |
|---|---|---|---|
| A1–A6 | `tests/service/test_synthesis_upgrade.py::test_operator_cli_and_central_service_on_populated_0_6_17` | The exact `rag service` inventory, preflight, plan, upgrade, retry and status commands on a store populated by the archived 0.6.17 code (`81beaf6`) | `030_pattern_synthesis.sql` applied, restore verified, original rows unchanged, retry empty, no synthesis rows; label `0.6.18` refused; old 0.6.17 central API served a scoped read and answered the unknown pattern tool with 404; new API served `memory_pattern_status` |
| A4 interruption, D restore limits | `tests/service/test_synthesis_upgrade.py::test_populated_0_6_17_upgrade_retry_old_code_recovery_and_restore_limits` | Interrupted migration and retry, old-code reads and writes on schema030, accepted-run recovery on a restored copy, pre-upgrade restore | 302 rows in 39 tables preserved; upgrade 2.22 s; post-upgrade writes absent from the pre-upgrade restore, as documented ([evidence](../../benchmarks/2026-10-31-pattern-synthesis/compatibility-evidence.json)) |
| A8, B1–B6, C1, C2, C4–C7, integrity check, D post-upgrade restore | `tests/service/test_synthesis_playbook.py` | The playbook's `rag pattern` commands through the real CLI, worker ticks through the central `rag service worker` loop, the `PB065-INTEGRITY` SQL block read from the playbook, and the PB-063 R1/R3 snippets on a schema030 dump | See below |

Observed in `test_synthesis_playbook.py` (2026-10-31, `1 passed in 14.14s`, exit 0):

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
- C4: after exhausted apply attempts the run was `error`/`apply_failed`/recoverable;
  `rag pattern recover` printed `re-queued (accepted)`; a second recover exited 1;
  the next tick applied it with still one provider call in total.
- Integrity check: `patterns` 2, every mismatch column 0, `open_runs` 0.
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

The C4 rehearsal simulates two waits with SQL on the owned database: the
provider backoff elapsing (`next_attempt_at`) and the worker's attempts running
out (`status='error'`). Those are the conditions the existing worker reaches on
its own after its configured backoff and attempt limit.

## Correction found during rehearsal

The first draft of C1 promised a `backfill` run after every request. An empty
window closes without a run. C1, the contract's as-built notes and the test now
state this.

## Not rehearsed

- Part B with a real model provider, and part D's pre-upgrade restore through the
  literal PB-063 R4 client switch with a 0.6.17 executable (the restore itself and
  old-code reads are rehearsed in the upgrade test).
- A live store, a systemd-managed central worker, or a multi-host deployment.

## Independent review

Pending: S2/T065-009 (coordinator-owned).
