# Maintenance backup verifier evidence

Issue: [#41](https://github.com/phense/agentic-rag/issues/41). Source:
`844a98643f19adc29c932fba845833518ac54ce9` (0.6.3). Candidate: 0.6.4,
`fix/p1-backup-verification`. Measurements use public synthetic data in owned
PostgreSQL databases; no production writes or private provider calls occur.

## Before and after

| Scenario | Source behavior | Candidate behavior | Sample |
|---|---|---|---|
| Restore exits 1 after loading plausible document/chunk counts | Reports `ok=true` | Reports `ok=false`, returncode 1; skips inventory | One verified red/green regression |
| Restore exits 0 with 98 documents and 200 chunks | Reads unrelated live counts and gives unqualified success | Counts only restored tables; reports `fidelity_verified=false` and a warning | One verified red/green regression |
| Complete 018 and 019 archives, followed by one additional live document | Live count differs from archive snapshot | Restored table inventory exactly equals the source snapshot captured before the dump; two restored documents remain two | Two real `pg_dump`/`pg_restore` rehearsals |

The initial two regression tests both failed for the intended reasons before
implementation. The targeted command
`uv run pytest -q tests/test_maintenance.py tests/test_maintenance_restore.py tests/test_backup.py`
passed **30 tests**. Four real restore rehearsals cover complete 018/019,
truncated archive and killed restore subprocess. The interruption test holds a
target-database advisory lock, observes `COPY restore_probe` waiting inside an
active transaction in `pg_stat_activity`, then kills `pg_restore`. It confirms
the restored probe table is absent after rollback and all scratch databases are
removed; a failure before the observed COPY cannot pass the test. Each source and scratch database
is newly created and identity-checked before removal. Source inventories remain
unchanged by verification; live changes after capture are excluded from fidelity
claims. No scratch database survives a successful cleanup.

The verifier restores with `--single-transaction --exit-on-error --no-owner
--no-privileges`, with a 900-second timeout and configured database host. All
public table counts include claims, sources, historical audits and optional schema
extensions. A missing documents/chunks table fails verification. Empty valid
corpora are allowed. New random scratch names are not reused or pre-dropped;
cleanup compares PostgreSQL OID and owner. Failure diagnostics retain categories
and exception types while omitting raw SQL, copied rows and credentials.

## Compatibility and limits

This is a code-only 0.6.3→0.6.4 update. Schema, dump format, CLI options, hooks,
queue semantics, MCP privilege levels and scheduler files remain unchanged.
Maintenance still exits zero; individual `ok`/`warning` fields carry failures.
The report adds `returncode` and `fidelity_verified` and replaces the misleading
`live` comparison with the restored inventory. Keep the old checkout/environment
and launchers for separately authorized code rollback. Existing processes retain
loaded code; no production adoption or service restart has been performed.

A strict zero-exit restore proves archive restorability, not complete source
capture. Ordinary historical archives have no same-snapshot source manifest;
full source fidelity, ownership and ACL preservation are explicitly unverified.
The rehearsal compares inventories only for the controlled source snapshot.
The verifier performs no recovery writes to the live store and never repairs
history. Cleanup refusal leaves the unrecognized database for operator inspection.

Baseline: `uv run pytest -q` passed **1,291 tests in 172.41 s**.
Candidate full suite passed **1,301 tests in 173.92 s**. The final backend-wait
fixture correction was then rechecked with all **30 affected tests in 3.41 s**;
production code did not change between those checks.
`node --test tests/test_opencode_plugin.mjs` passed **7 tests**.
`uv lock --check` and `git diff --check` passed.

Independent whole-diff review found two Medium issues: a stale second handbook
description and a timeout fixture that did not prove active restore interruption.
Both were corrected and independently re-reviewed. The final review reports
no Critical, High, Medium or Low findings. No merge or production adoption
is inferred from these results.
