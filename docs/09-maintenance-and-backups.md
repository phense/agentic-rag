# Maintenance & backups

*What you'll learn: what `rag backup` actually writes and where, how the
optional offsite copy works, the difference between `rag restore` and the
automatic restore-*test*, what `rag maintenance` does on every run (and why
it's deliberately small), and how to schedule both on macOS and Linux.*

## `rag backup`: local always, cloud when you ask for it

```bash
rag backup
```

runs `pg_dump -Fc` against your configured database and writes a timestamped
dump — `agentic_rag-YYYYMMDD-HHMMSS.dump` — into `[backup] local_dir`
(default `~/.agentic-rag/backups`). That local copy always happens; there's
no configuration required to get it.

A second, offsite copy is **opt-in**. Set `[backup] cloud_dir` in
`config.toml` to a path you control — a mounted network share, an
externally-synced folder, whatever your setup already backs up — and every
`rag backup` run also copies the dump there, once the mount is confirmed
present:

```toml
[backup]
cloud_dir = "/path/to/your/cloud/dir"
```

If `cloud_dir` isn't set, backups are local-only and silent about it — that's
the expected default, not a degraded state. If it *is* set but the parent
path isn't mounted when the job runs, the local dump still succeeds and a
warning is recorded to `~/.agentic-rag/state/backup_warning` (surfaced by
`rag status`) instead of failing the whole run or silently skipping the
offsite copy. The warning clears itself the next time a cloud copy actually
lands.

Each run also rotates old dumps, and the two locations use different
policies on purpose:

- **Local** (`[backup] keep_local`, default `7`) — keep only the newest N
  dumps. Local disk is meant for fast, recent recovery, not long history.
- **Cloud** (`[backup] keep_daily` / `keep_weekly`, defaults `14` / `8`) —
  keep the newest 14 daily dumps *plus* up to 8 older ones, one per
  ISO week, for dumps that fall outside that daily window. That buys real
  calendar depth (months of weekly checkpoints) without keeping every
  nightly dump forever.

`rag backup --install-launchd` additionally installs (and loads) the
launchd job described below — macOS only — and then runs the backup
immediately either way.

## `rag restore <dump> --yes`: the real recovery path

```bash
rag restore ~/.agentic-rag/backups/agentic_rag-20250101-033000.dump --yes
```

restores a dump straight into your **live**, configured database, via
`pg_restore --clean --if-exists --single-transaction`. Every piece of that
is deliberate:

- **`--yes` is mandatory.** Without it the command refuses outright — there
  is no interactive confirmation prompt to fat-finger past.
- **`--single-transaction`** makes the restore all-or-nothing: if it fails
  partway through, Postgres rolls the whole thing back rather than leaving
  the database half-dropped.
- **`--clean --if-exists`** drops existing objects before recreating them
  from the dump. `pg_restore` connects to a database that already exists —
  it doesn't create one — so point `config.toml` at the right `db_name`
  (run `rag init-db` first if you're restoring onto a fresh install) before
  restoring.

This is the command you reach for in an actual incident. It is intentionally
separate from — and touches nothing in common with — the automatic
restore-*test* below, which never runs against your live database.

## `rag maintenance`: small on purpose

A Postgres + pgvector store doesn't need most of what a file-based wiki
needs to stay healthy: no dedup detector for markdown drift, no link-lint,
no graph rebuild, no embedding-mirror sync. Writes are transactional, edges
are rows, not `[[wikilinks]]` to break. So `rag maintenance` owns exactly
three residual jobs, and nothing else:

| Step | What it does |
|---|---|
| **Worker drain tick** | Runs the single-writer worker (`python -m agentic_rag.worker`) once, with a 15-minute timeout. The worker is otherwise spawned only by session hooks, so on a quiet day — no Claude session, or Ollama was briefly down when a document was written — embed-retries and queued curation would just sit there. This tick unsticks them. The worker is itself a flock singleton, so if one is already running, this is a clean no-op — never a second pipeline. Skip it with `--no-worker`. |
| **Log rotation** | Any `*.log` file under `~/.agentic-rag/log/` past 5 MiB is moved to `<name>.log.1` (one prior generation kept) and started fresh. Only touches agentic-rag's own logs. |
| **Weekly restore-test** | On Sundays — or with `--verify-backup` — restores the newest local archive into a fresh, uniquely named scratch database using `--single-transaction --exit-on-error`. Nonzero exit, timeout, missing canonical tables or cleanup failure is reported as a failed check. All restored public tables are counted in one read-only snapshot. Cleanup checks the scratch database OID and owner; it never drops a pre-existing target. A zero restore exit proves archive restorability. `fidelity_verified=false` and a warning explicitly state that complete source fidelity, ownership and ACL preservation remain unverified. Existing archives contain no same-snapshot source manifest, so this check never compares their row counts against a changing live database. |

The whole run is wrapped in a single-flight lock
(`~/.agentic-rag/state/maintenance.lock`): if another maintenance run is
already holding it, this run logs a skip and exits — no queueing, no
overlap. Each of the three steps is isolated from the others — one failing
step is logged and recorded in the run's audit line, but never aborts the
rest of the run and never turns into a non-zero process exit. `rag
maintenance` always exits `0`, on purpose, so a scheduler (launchd, cron)
never sees it as a failed unit and never gets wedged retrying it. Every run
still writes a structured record to `~/.agentic-rag/log/maintenance-audit.jsonl`,
so a real failure is visible to anyone who looks — it just doesn't surface
as a process exit code.

Deliberately **not** here: periodic `VACUUM`/`ANALYZE`/`REINDEX` (autovacuum
covers this at this scale), refuted-document purge, error-job requeue, or
any autonomous near-duplicate merge. Those stay manual and explicit — `rag
purge`, `rag review` — rather than something a nightly job does to your data
unattended.

Flags: `rag maintenance --verify-backup` forces the restore-test regardless
of weekday; `--no-worker` skips the drain tick; `--install-launchd`
installs the launchd job (see below) and returns — it does not also run
maintenance in that same invocation.

## Scheduling

**macOS**: `rag install` automatically installs and loads the **backup**
launchd job (`com.agentic-rag.backup`, daily at 03:30) as part of the normal
install flow — nothing further to do for backups. The **maintenance** job
is a separate, one-time step: run

```bash
rag maintenance --install-launchd
```

once, to install `com.agentic-rag.maintenance` (daily at 04:00 — deliberately
half an hour after the backup job, so the Sunday restore-test has that
morning's fresh dump to check). Both plists are written to
`~/Library/LaunchAgents/`, each pointing at the `rag` binary path resolved
fresh at install time — so a recreated virtualenv doesn't leave launchd
pointing at a dead interpreter.

**Linux**: there's no launchd, so both jobs are set up manually. See
[Scheduling on Linux](deploy/scheduling-linux.md) for copy-pasteable `cron`
lines and `systemd` user-timer units for both `rag backup` (03:30) and `rag
maintenance` (04:00) — the same schedule the macOS launchd jobs use.

## `pg_dump` / `pg_restore` binary resolution

Both `rag backup` and `rag maintenance`'s restore-test need `pg_dump` and
`pg_restore`. They're resolved in this order:

1. **`PATH`** — if the binary is already on your `PATH`, that wins.
2. **`[pg] bin_dir`** in `config.toml`, if you've set it.
3. **Platform fallbacks** — on macOS, common Homebrew keg-only paths
   (e.g. `/opt/homebrew/opt/postgresql@17/bin`); on Linux, distro package
   layouts (e.g. `/usr/lib/postgresql/*/bin`, newest version first).

If none of those resolve, the command fails with an explicit error telling
you to set `[pg] bin_dir` or fix your `PATH` — never a silent skip. If a
`pg_dump`/`pg_restore` invocation itself fails (bad auth, disk full), the
real stderr from the tool is surfaced in the error, not just an exit code —
important for a job that mostly runs unattended.

## Checking backup health from `rag status`

```bash
rag status
```

reports the newest local dump filename (or `—` if none exist yet) and any
pending cloud-mount warning. It's the fastest way to confirm last night's
job actually ran before you trust it.

## Next →

[10 · Architecture](10-architecture.md) — the schema, the role matrix, HNSW
+ full-text indexing, the write gateway, and how the worker, hooks, and MCP
servers fit together.

### Upgrading the restore verifier

Version 0.6.4 is a code-only upgrade from 0.6.3, with compatible schema 001–019,
existing archives, maintenance flags, weekly schedule and always-zero process exit.
No dump rewrite, database migration, client configuration change or scheduler
reinstall is required. Existing 018 archives are restored at their original schema;
the verifier does not apply new migrations to them. A successful empty corpus is
restorable too. Review `ok`, `returncode`, `restored`, `warning` and
`fidelity_verified` in the maintenance audit. Consumers of the former `live`
comparison must switch to the explicitly qualified archive inventory.

Adopt the reviewed package separately from PR merge approval. Keep the previous
checkout/environment and stored launcher paths for code rollback. Do not run
`rag restore` to test a backup: it targets the configured live store. Verification
uses a fresh scratch database and never writes knowledge, pins, queues or audits
in the source. Interrupted restores roll back; failed cleanup is reported for
operator inspection rather than deleting an unrecognized database.

[Issue41 verification](verification/maintenance-backup.md) records owned-source
018/019 restore and failure rehearsals and the limits of this smoke test.
