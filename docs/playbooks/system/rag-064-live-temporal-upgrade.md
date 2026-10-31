# PB-064-LIVE: Upgrade the existing central service and enable temporal search

## Identity and scope

- Class: development and system; retained for existing-installation upgrades.
- Origin: maintainer request on 2026-10-31 to deploy and activate PR87 before merge; RAG-064 AC-007, following PB-063-UPGRADE.
- Audience/owner: the DBA/operator; the maintainer authorizes the live maintenance window and merge.
- Target: package0.6.17/schema029, reviewed application source `e51003a`; source0.6.15/schema028. Both API installations on the identified `mcp-server` Hetzner VM are in scope. The canonical worker remains inactive and its cutover gate stays absent.
- Readiness deadline: independent content review and full-copy rehearsal before stopping the APIs or applying live DDL.
- Last edited: 2026-10-31. [Review and execution evidence](rag-064-live-temporal-upgrade-review.md).

## When to use / when not to use

Use this bounded deployment procedure for the two identified stores. Version0.6.17
contains the additive029 migration from0.6.16, so the direct0.6.15→0.6.17 upgrade
applies that one migration. Temporal search itself adds no tables, re-embedding or
stored-content rewrite. A source already on0.6.16/schema029 needs no migration.
An intermediate running0.6.16 service is unnecessary; the029 SQL is byte-identical.
The supported operator accepts source0.6.15 and0.6.16.

Stop for an unknown source schema, owner, extra live writer, failed restore/hash
check, or insufficient storage. Do not merge stores, switch the local production
client, start the canonical worker, or modify embedding/reranker settings.

Terms: the canonical store is the shared knowledge database; the dashboard store
is its separate existing rehearsal installation. A manifest records row counts,
content hashes, grants, owners and sequences. A fence temporarily makes returning
connections read-only. Rehearsal uses full copies with generated ownership markers;
only those owned copies are removed automatically.

## Before starting

Resolve `ssh mcp-server` and verify `hostname`, filesystem space and service units.
On this deployment, `agentic_rag` is owned by `administrator`, and
`rag_dashboard_rehearsal_20261030` by `rag`. Both must end in
`028_reranker_settings.sql`; PostgreSQL major17 and vector identity must match the
backup. Keep at least three database sizes free for each backup/restore operation.

Define these shell inputs on the VM:

```sh
RELEASE=/opt/agentic-rag-releases/0.6.17-e51003a
PREVIOUS=/opt/agentic-rag-releases/0.6.15-5390a6f
PROOF=/var/lib/postgresql/rag64-live-20261031
OPS=/var/lib/agentic-rag/upgrade-20261031-rag64
```

Create a new private DBA directory and copy the current two configurations to
`PROOF/canonical-operator.toml` and `PROOF/dashboard-operator.toml`, owned by
postgres mode0600. Record source/config/auth-file hashes, symlink targets, running
units, timers and all connected database clients. Store a root-only archive of
configuration, launcher scripts, unit overrides and the backup helper under OPS.
Keep PREVIOUS and its virtual environment intact. Prepare RELEASE from the exact
reviewed Git tree and run `uv sync --frozen --offline --no-dev --python /usr/bin/python3.13`.
Compare every archived file hash to its Git source; confirm package metadata0.6.17.

Install the [reviewed DBA driver](../../verification/issue64/live-upgrade.py.txt)
as `PROOF/live-upgrade.py`, postgres-owned0600. It uses fixed deployment database
identities and existing verified-backup/fence/migration code. Run it with:

```sh
sudo -u postgres env PYTHONPATH="$RELEASE" "$RELEASE/.venv/bin/python" \
  "$PROOF/live-upgrade.py" preflight canonical --directory "$PROOF"
```

Replace the mode/target with the table entries below. These operator commands use
DBA credentials only locally through peer authentication. Never run the API as DBA.

## Decision paths and actions

| Step | Actor/target and action | Expected observation | Failure/next step |
|---|---|---|---|
| L1 | Operator: run `preflight canonical`, then `preflight dashboard` | Ready;28 migrations, checked owner, private inventories | Unknown state or blockers: stop |
| L2 | DBA: run `rehearse canonical`, then `rehearse dashboard` while the old APIs remain available | Each snapshot independently restored; full copy migrated029 with unchanged original rows/ACLs/owners; empty retry; actual old0.6.15 before/after reads and new legacy reads equal; owned copy removed | Retain failed artifacts; fix and use a fresh proof directory before live operations |
| L3 | Operator: confirm no backup is running; record and stop enabled `nwb-rag-backup.timer`, then `agentic-rag-api.service` and `agentic-rag-59-api.service` | Both APIs inactive, worker still inactive, no remaining clients in either database | Wait for graceful shutdown; inspect remaining clients; do not terminate unowned sessions or bypass the fence |
| L4 | DBA: run `apply canonical`, then `apply dashboard` | Fresh final backups independently restored; migration list exactly029 (or empty on committed retry); all original rows/rights/owners retained; second migration call empty | Keep both APIs stopped. Determine committed marker per recovery below |
| L5 | Operator: append `[temporal]`, `enabled = true`, `timezone = "Europe/Berlin"` to both live configs after confirming the section is absent; preserve ownership/mode | Config loader reports enabled/Berlin. Auth policy, provider and model settings have unchanged hashes/values | Existing conflicting temporal section: edit that section explicitly and revalidate, never append a duplicate |
| L6 | Operator: `ln -sfnT "$RELEASE" /opt/agentic-rag` and the same for `/opt/agentic-rag-59`; retain existing systemd launchers/overrides | Both links resolve to RELEASE; launchers retain their loopback ports and trusted TLS-proxy settings | Before starting, restore links/config from OPS if incorrect |
| L7 | Operator: start both APIs, using their recorded service names | Services active; HTTPS8443/8449 health200, capabilities0.6.17/schema029 with existing credentials | Stop both on failure; use code/config rollback or repair forward |
| L8 | Operator: verify scoped REST and RO-MCP reads, unauthorized/cross-scope rejection, automatic EN/DE interpretation, explicit hard filter, no-intent/off behavior, known-memory evidence contract and dashboard login/Settings read | Authenticated success through real TLS/services; temporal explanation uses Europe/Berlin by default; known content/references unchanged; no permission widening | Keep results private; investigate any mismatch before merge |
| L9 | DBA: run `post canonical`, then `post dashboard` | Original core hashes, original grants/owners and migration timestamps unchanged after traffic; operational rows distinguished | Core drift blocks merge; preserve snapshots and investigate |
| L10 | Operator: produce and validate a fresh upgrade recovery package with the existing backup publisher below; then restart the previously enabled backup timer | New package metadata0.6.17/schema029, independently restored; new release/recovery configuration included; timer enabled, worker unchanged | Retain rollback release/dumps; fix backup before merge |

The daily backup publisher keeps an existing verified package for the same day.
Running its systemd service again would only revalidate the old0.6.15 package.
For L10, make a distinct root-owned package, then run the normal daily service:

```sh
sudo python3 - <<'PYBACKUP'
from pathlib import Path
import fcntl, importlib.util, json, os, pwd, stat
os.umask(0o077)
spec = importlib.util.spec_from_file_location('rag_ops', '/usr/local/lib/nwb-rag-ops/rag-backup.py')
ops = importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)
root = Path('/var/backups/agentic-rag/upgrade-0.6.17-20261031')
root.mkdir(mode=0o700, exist_ok=True)
assert root.is_dir() and not root.is_symlink()
# The temporary dump producer runs as postgres and must traverse its parent.
# Final published packages remain root:root0700 with root:root0600 files.
os.chown(root, 0, pwd.getpwnam('postgres').pw_gid); root.chmod(0o710)
# Use the same job lock and secure publisher as the regular service. publish()
# resets every file and directory to root ownership and restrictive modes.
with (ops.STATE.parent/'backup.lock').open('w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    package = ops.publish(root, '2026-10-31', ops.produce)
    info = ops.validate_package(package)
    assert info['restore_verified'] is True
    assert json.loads((package/'database.package-version.json').read_text())['installed_version'] == '0.6.17'
    for item in [package, *package.iterdir()]:
        st = item.stat()
        assert st.st_uid == st.st_gid == 0
        assert stat.S_IMODE(st.st_mode) == (0o700 if item.is_dir() else 0o600)
print('fresh_upgrade_package_restore_verified_and_root_private')
PYBACKUP
sudo systemctl start nwb-rag-backup.service
sudo systemctl start nwb-rag-backup.timer
```

Keep that separately named package with the upgrade evidence; it is outside the
daily date-based rotation. It covers the canonical database. The dashboard dump
and its separate configuration archive are retained in PROOF/OPS. Before L9,
run only the bounded read/authentication probes. Other clients can reconnect
when the APIs restart; any concurrent ingest/save may trip the conservative
post-traffic hash check. Keep the mismatch and distinguish legitimate writes
from an upgrade defect before claiming preservation; do not broaden exclusions
to hide a change in knowledge or audit records.

The maintenance interruption begins at L3. The databases are upgraded sequentially
with both APIs stopped. L4 commits each database independently; there is no
cross-database transaction. Never start one API on the wrong schema while the other
store still needs migration. Activation keeps the known LOW-031..035 limitations
in [Issue75](https://github.com/phense/agentic-rag/issues/75). Version-like strings
can suppress interpretation; explicit `temporal=off` restores legacy query handling.

## Interruption, recovery and rollback

The migration marker and029 objects commit in the same transaction. Inspect
`schema_migrations` and `to_regclass('public.claim_history')` in each identified
database. Marker absent/table absent means no migration commit. Both present mean
that store committed; keep it and complete the other store. A mixed marker/object
state is a blocker. Preserve all original evidence files.

The driver refuses incomplete dumps or existing result files. For an interruption,
choose a new private proof directory, copy the configs and retained rehearsal
results with their origin clearly recorded, and make fresh final backups. Schema029
returns an empty migration list. Never overwrite a dump to retry. A hard process
kill can leave `default_transaction_read_only=on`; compare the database setting to
the recorded pre-operation setting and restore only that setting after all writers
are stopped. Do not silently clear an unexplained fence.

Code/config rollback preserves post-upgrade writes: stop both APIs, restore their
saved configuration files, repoint both symlinks to PREVIOUS and restart. Actual
0.6.15 reads against the upgraded copy are tested in L2;029 stays installed. Check
health and authenticated reads. Old writes record direct evidence history as
specified by [PB-063](rag-063-source-evidence-upgrade.md). Re-enable the prior timer.

A pre-migration database restore loses writes after that backup. It is a separate
recovery decision requiring approval of the recovery point. Keep the upgraded store
intact, use the verified dump/manifest and R1–R4 in PB-063, and redirect every client
to the separately restored database with0.6.15 code. Never restore over the live
store or attempt a destructive SQL downgrade. Full live disaster recovery is outside
this deployment's acceptance; verified copy restores and code rollback cover its
required reversible paths.

## Escalation and preserved evidence

Stop before merge for any content/rights mismatch, failing TLS/auth/read probe,
service failure or unverified backup. Report it to the maintainer in the current
conversation with sanitized IDs/counts. Keep full inventories, dumps, database
names and content private on the VM. Public evidence may contain only hashes,
aggregate counts, source revisions, commands, outcomes and explicit limitations.

## Completion

Both APIs must run0.6.17/schema029 with temporal auto enabled/Berlin; scoped
REST/MCP/dashboard checks, data preservation and the daily restore-verified backup
must pass. Retain the old release, configs and dumps; preserve inactive worker and
absent worker-cutover gate. Commit this procedure and sanitized execution evidence
to PR87, verify its checks, then merge under the maintainer's explicit instruction.

## Maintenance and sources

Recheck on changes to database ownership, deployment paths, launchers, operator
JSON/backup interfaces, schema, temporal defaults or source eligibility. Sources:
[upgrade implementation](../../../agentic_rag/service/upgrade.py),
[029 SQL](../../../sql/029_source_evidence.sql),
[temporal reference](../../temporal-query.md), and the archived0.6.15 source retained
on the VM. Initial live inventory:2026-10-31; no new application behavior is required
for this deployment path.
