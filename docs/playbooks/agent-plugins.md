---
title: Install or recover a native agentic-rag client
type: playbook
audience: administrators
version: 0.6.22
---

# PB06801: Install or recover a native agentic-rag client

## Identity and scope

- Class: system.
- Origin: Issue #68, FR01–09 in [the specification](../specs/6-10-agent-plugins/spec.md).
- Owner/audience: deployment administrator; agent user for status/cancel recovery.
- Target: 0.6.22/schema035; inherited plugin protocol024, owned plugin directories and an explicitly enrolled client.
- Readiness deadline: before activating a new client or upgrading a central server.
- Last edited: 2026-11-02 (optional daemon section corrected after S06808 review; L0/L1 physically rehearsed on owned copies. Renewed content review, L2/L3 real-model rehearsal and final delivery/performance gates remain open).
- Evidence: [review and rehearsal record](evidence/agent-plugins.md).

## When to use / when not to use

Use for packaging an existing Python installation, staged client/server updates,
or a tool that reports a waiting handle. Do not use it to import independent
stores, merge department permissions or cut over production writers. Those actions
retain the [6.0 deployment/upgrade gates](../verification/issue58-service.md).
An unavailable native model login blocks claims about that host's interactive UI;
it does not justify copying another department's credentials.

## Before starting

1. Choose an existing Python environment with agentic-rag0.6.22 and run
   `rag --help` and `rag plugin --help` in it.
2. Check the enrolled token's private permissions and intended domains/projects/
   teams with the administrator; do not print the token. Use the existing
   `rag service client-config` command for a remote or loopback server.
3. Choose a new owned package directory, host (`claude`, `codex`, `gemini`) and
   explicit absolute client config path. Keep config, credentials and spool
   outside the generated package.

Intentional parameters in examples: `/opt/rag-client/bin/python`,
`/home/agent/.agentic-rag/client.toml`, `/home/agent/plugins/agentic-rag`. Replace
them with this client's inspected paths. Authority covers only the chosen
package and explicitly selected host installation; existing foreign settings
and pending evidence remain outside that boundary.

## Decision paths and actions

| Step | Actor/target and action | Expected evidence | Failure/next step |
|---|---|---|---|
| P01 | Administrator previews package with the command below | `preview:true`, host and exact file paths; no files created | Resolve wrong paths/host before applying |
| P02 | Administrator repeats with `--apply` | Native manifest/hooks/MCP plus `.rag-package.json` ownership record | A foreign or modified file is a conflict: stop, inspect it, do not overwrite |
| P03 | Administrator runs `rag plugin doctor --host claude --destination /home/agent/plugins/agentic-rag` | `status:ok`; owned file hashes match | Stop activation on any conflict or missing file |
| P04 | Administrator activates the owned package through the host's native mechanism below | Host lists/discovers agentic-rag; fresh session reports authorized context or explicit waiting/offline state | Keep old integration until new one is verified; avoid enabling both capture paths |
| P05 | Agent invokes a read tool, then native manual compression or a controlled automatic boundary | Durable original source/checkpoint, correct continuation, source extraction status distinct from current knowledge | Retain original transcript and local spool on any missing capture/ACK; use recovery below |
| P06 | Administrator tests scoped main/read-only and foreign-department denial | Main tools behave within scope; RO has no mutation/cancel/capture; foreign data denied | Disable new integration and inspect policy; never broaden it to make a test pass |

Preview:

```sh
rag plugin install --host claude \
  --destination /home/agent/plugins/agentic-rag \
  --python /opt/rag-client/bin/python \
  --config /home/agent/.agentic-rag/client.toml
```

Use `--read-only` when packaging a read-only agent. Update with the same arguments
and `plugin update`; omitted wiring options retain the recorded paths and RO
choice. `plugin uninstall ... --apply` removes only unchanged owned package
files and retains the bounded previous generation in `.rag-package.json`.
Disable the package in the host before uninstalling its generated files. The
record is recovery evidence, not a copy of native user settings or source data.

Native activation:

- Claude: validate with `claude plugin validate /home/agent/plugins/agentic-rag`,
  then use `claude --plugin-dir /home/agent/plugins/agentic-rag` in an owned test
  workspace, or publish the package through the team's native marketplace.
- Codex: place the package in a local marketplace, add that marketplace with
  `codex plugin marketplace add /path/to/marketplace`, then
  `codex plugin add agentic-rag@marketplace-name`. Validate the actual installed
  CLI's `plugin --help`; keep the existing Codex installer as a fallback.
- Gemini: use `gemini extensions install /home/agent/plugins/agentic-rag`, review
  the host's trust prompt, then restart and inspect `gemini extensions list`.
  Do not enable automatic extension updates until the matching Python engine has
  passed the staged upgrade. agy uses `rag install --agy`, not this command.

## Interruption, recovery and rollback

| Observation | Safe action and result |
|---|---|
| `waiting:true,durable:true` | Retain `request_id`; call `memory_request_status`. Completed returns the original result; pending/running means keep waiting within a finite tool deadline. Do not submit a new envelope. |
| `local.<uuid>,durable:false` or lost ACK | Keep the local outbox. The same status tool reconciles its unchanged envelope; cancellation first reconciles whether the server accepted it. |
|429/507 before acceptance | Preserve input, retry with bounded backoff after pressure clears. Poll no faster than once per second per waiting tool; share the uploader's12/s allowance across sessions. |
| Cancel/expiry | Cancel an owned handle once; repeating it does not append audit rows. `completed` means effects already committed. `expired`/`result_expired` means the finite result window ended; inspect canonical state before intentionally issuing a new mutation. |
| Credential rotation/logout/scope change | Old authority cannot execute or release results. Retain the old partition as recovery evidence; enroll a fresh profile explicitly. Never retimestamp/rekey an ambiguous mutation automatically. |
| Full local spool or malformed/rewritten recording | Retain host recording and pending spool. Drain existing source work with `rag service spool --flush`; repair or recover source input explicitly. Removing the plugin does not make that evidence safe to delete. |
| Interrupted package update | Keep `.rag-package.json` and its bounded recovery generation. Preview `rag plugin recover --host claude --destination /home/agent/plugins/agentic-rag`, then repeat with `--apply` to restore the recorded owned generation. A mismatch is a stop condition, not permission to overwrite foreign content. |

Before a server upgrade, take `rag service verified-backup` with the inspected
source version and perform the existing verified upgrade/strict restore rehearsal
on an owned copy. Schema023→024 is additive. Stop writers only within the
explicitly approved deployment window. Upgrade server first, verify synchronous
compatibility/queue capabilities, then update clients and native packages.
For code rollback leave024 installed, disable new client queue use by returning
to the prior connector/package, and retain pending handles until reconciled.
Do not drop tables or replay unconfirmed mutations during rollback.

## Escalation and preserved evidence

Escalate unknown native event formats, failed original-row/ACL comparisons,
request effects without a completed receipt, foreign data visibility or a
package ownership conflict to the maintainer. Preserve version, event names,
request/source IDs, stable error codes, timing, file hashes and owned test logs.
Keep prompts, recordings, tokens and unrestricted results out of public issues.

## 0.6.20 to 0.6.21: native source-origin gate

Older capture code can classify a native compaction summary or API mirror as
user testimony. Keep every original recording and spool. Migration033 corrects
current selection when a replacement's **only** sources have been proven to be
generated host context. Ordinary refutation, removal and expiry still do not
revive an older value. No assertion, edge or evidence quote is rewritten.

### O1: stop and inventory the existing installation

Inventory every local miner, central worker, uploader, direct DB client, active
agent/MCP process and retained recording/spool. Stop capture, upload and mining
on **every** listed host before the snapshot; retain that process list. Use the
existing [verified backup and recovery procedure](../verification/issue58-service.md).
Then install0.6.21 and run the public migration command on the DB host:

```sh
rag service --config /owned/operator.toml upgrade --source-version 0.6.20 \
  --dump /owned/origin-pre-upgrade.dump --apply --writers-stopped
```

Expected: only `033_trusted_replacements.sql` applied, independent restore
verified and original rows unchanged. An interrupted migration rolls back; use a
new dump path for retry. Restart all listed Python/agent processes onto0.6.21
before activation; reuse the per-environment process gate in
[PB-067 B1](system/rag-067-extraction-policy.md#b1-mining-gate), expecting0.6.21.
For editable installs or clock changes, restart unconditionally. Keep workers
and uploaders stopped through O4. Unknown hosts or missing recordings block
activation of their streams.

### O2: export remote recordings and identify their exact namespaces

For a local recording use `session:<original-session-id>`, never its filename.
For a remote client, first list the stopped spool's `sources` rows on **that
client host** with read-only SQLite. Replace `SPOOL`, `PARTITION`, `SESSION` and
paths below with its inspected values; do not read or print its token.

```sh
python3 - SPOOL <<'PYLIST'
import json, sqlite3, sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).absolute().as_uri() + '?mode=ro', uri=True) as c:
    rows = c.execute('SELECT partition,session,project,length(raw) bytes FROM sources ORDER BY partition,session').fetchall()
print(json.dumps(rows))
PYLIST
```

Export each selected row using the upgraded client Python environment. The
exporter checks every pending local window, including blocked work, against the
original bytes. It refuses missing prefixes, changed cursors or more than256
pending windows. It never advances a cursor, acknowledges work or changes the
spool. Both output paths must be new and inside an owner-only directory.

```sh
python3 - SPOOL PARTITION SESSION /owned/original.jsonl /owned/export.json <<'PYEXPORT'
import sys
from pathlib import Path
from agentic_rag.source_origin import export_spool
from agentic_rag.service.upgrade import private_json
spool, partition, session, recording, report = sys.argv[1:]
if Path(report).exists():
    raise FileExistsError(report)
result = export_spool(spool, partition, session, recording)
private_json(report, result)
PYEXPORT
```

Copy both private files unchanged to the DB host over the installation's
existing SSH connection. Obtain namespaces from retained **server rows**, using
its operator Python environment and configuration:

```sh
python3 - /owned/operator.toml /owned/streams.json <<'PYSTREAMS'
import sys
from pathlib import Path
from agentic_rag import db
from agentic_rag.config import load_config
from agentic_rag.service.upgrade import private_json
cfg = load_config(Path(sys.argv[1]))
if cfg.service_mode == 'client':
    raise ValueError('local operator config required')
with db.connect(cfg) as c:
    c.execute('SET TRANSACTION READ ONLY')
    rows = [dict(r) for r in c.execute("SELECT session_id,owner_namespace,project,payload->>'session_id' client_session,count(*) windows FROM service_windows GROUP BY session_id,owner_namespace,project,payload->>'session_id' ORDER BY session_id LIMIT 1001")]
if len(rows) > 1000:
    raise ValueError('stream inventory overflow; keep uploaders stopped')
private_json(sys.argv[2], rows)
PYSTREAMS
```

Match `client_session` and `project` to `export.json`, and verify the enrolled
uploader against the operator's client inventory. Use that row's **complete
`session_id`** as the namespace; it starts with `svc1:`. Multiple matches require
resolving the uploader; never pick one by a user label. An entirely offline
stream has no server row: retain its spool and keep it stopped until the
administrator explicitly identifies its enrollment and obtains a complete
server-side inventory. This procedure does not guess a namespace.

### O3: preview and quarantine each covered stream

Run on the DB host with its local operator configuration. For remote work,
replace the example namespace with the exact O2 `session_id`.

```sh
rag service --config /owned/operator.toml source-origin \
  --transcript /owned/original.jsonl --namespace 'session:original-session-id' \
  --output /owned/origin-preview.json
```

Expected: `ready:true`, no `metadata_conflicts`, `uncovered_source_keys` or
uncovered windows/batches, and `overflow:false`. The preview reads current DB
state and changes nothing. It checks all retained windows of that stream, all
accepted batches and every existing source identity against the recording.
Compare the DB windows with the O2 inventory; `export.json` separately proves
the stopped client's unacknowledged windows. Retain both reports and their
matching `recording_sha256`: the export and DB preview SHA-256 values must be
identical. Stop on a mismatch; obtain the correct original bytes before apply.
A green preview is bounded to this recording and
namespace, not a census of other clients or unavailable histories.

```sh
rag service --config /owned/operator.toml source-origin \
  --transcript /owned/original.jsonl --namespace 'session:original-session-id' \
  --output /owned/origin-applied.json --apply --writers-stopped \
  --expected-sha256 '<recording_sha256 from preview>'
```

The gateway withdraws only proven generated sources, including tombstones for
old batches. Accepted batches retain their replay identity and make no second
provider call; assertions backed by an already inactive source enter `review`
and create no replacement edge. New inference excludes quarantined fragments.
An independently supported assertion can remain eligible.

### O4: verify before restarting

Inspect `affected_claims` and `temporal_dependents` in the apply report. Compare
`eligible_before` with `eligible_after`: a previously hidden original can
resurface only through the migration033 exception above and its own truth/scope
gates. Supersession with genuine independent evidence stays authoritative.
If an original expected to be current still has `eligible_after:false`, inspect
its own status, scope, expiry and independent evidence first. An already
refuted/removed generated source retains its earlier reason, so it does not
receive the correction marker (LOW-059). Keep that stream stopped and preserve
the report for explicit operator recovery; do not reactivate generated evidence
as a shortcut. After quarantine, do not change the source state or reason through
normal review: the current marker carries the correction, and overwriting it can
hide the original again. Any necessary later change requires repeating the
current-fact checks and reviewing LOW-059 before activation.
Use each reported `document_id` or slug with `rag evidence show`. Use
`generated_source_keys` (not `generated_source_ids`) for
`rag evidence history DOCUMENT --source SOURCE_KEY`; retain the private history.
Then rehearse pending-window replay on the owned populated copy, verify no
second provider call for accepted work, and compare original rows and permissions
against the migration inventory. Before restarting covered streams, create a
post-quarantine recovery point with a new, private path:

```sh
rag service --config /owned/operator.toml verified-backup --source-version 0.6.21 \
  --output /owned/origin-post-quarantine.dump
```

Require `restore_verified: true`; retain the dump and manifest with the private
quarantine reports. Failure keeps the streams stopped. Restart only the covered,
upgraded streams.

A metadata or coverage conflict refuses apply before any source write. Repair
only by obtaining the correct original recording/enrollment; do not edit JSONL,
split it with renumbered lines, clear queues or reset session IDs. Atomic audit
failure can be retried with the same digest and a new output path. Already
inactive sources produce no duplicate source-state audit. More than256 retained
windows/batches/affected claims or64MiB of recording, or more than4096 generated
records, is outside this bounded procedure: preserve it and keep that stream
stopped for an explicit larger-history recovery plan.

For code recovery retain033 and removed sources.0.6.20 can read the corrected
predicate but can misclassify new host records and accept removed-source
replacements: keep capture/mining stopped until0.6.21 is restored. Restoring the
pre-upgrade backup also restores old trust and loses later writes; repeat this
origin gate after the existing explicit restore/cutover procedure.

## 0.6.21 to 0.6.22 lexical-search upgrade

This step is independent of source-origin quarantine. Migration034 replaces
four SQL search functions and the existing source-write permission helper
atomically. Migration035 changes only the existing document policy expressions
and adds a pure, invoker permission helper. Permission JSON is read lazily once
per statement input, including each execution of a prepared generic plan. The
helper deliberately permits PUBLIC execution: it evaluates caller-supplied
arguments and reads no data. Existing table grants, roles and the other RLS
policies stay in force. Neither migration changes original rows, vectors, scopes,
installation configuration or wire fields. Its retrieval-local
`jit=off` setting bounds compilation cost and is restored automatically on return;
raw/contextual vector gates keep eligibility before ranking and limits. On
pgvector0.8+ they continue the ANN scan past filtered neighbours. An incomplete
256-candidate pool triggers exact sorting; supported0.7 installations use this
exact path directly. Caller scan/memory caps remain unchanged. The fallback
preserves filtered recall but can require checking the whole eligible corpus;
the dense-fixture work bound is not a general latency guarantee. Existing0.6.21 readers accept
schema035. New0.6.22 service processes refuse access until034 and035 are installed.
Prepare0.6.22 in its own environment and reinstall editable packages so their
distribution metadata agrees with the source. Retain the0.6.21 environment.
Rebuild disposable rehearsals that already applied an earlier unpublished034:
the migration ledger records filenames and will not reapply an edited file.
Do not clear ledger rows or replay edited migration files on an existing
installation. The narrowly scoped035 recovery below is the only explicit SQL
reapplication in this procedure.

A non-superuser deployment owner needs the existing DBA-prepared vector
extension/preload setup from the [service installation procedure](../13-central-service.md#start-and-verify-the-central-service).
For independent restores, supply an empty, owner-accessible vector-only
template of the same extension version with `--verification-template TEMPLATE`
on both `upgrade` and `verified-backup`. The template must contain no application
tables, and `vector` must be installed in `public`; see the
[restore-template preparation](../15-dashboard.md#restore-verification-privileges).
Migration034 uses registered pgvector settings; do not grant superuser
or parameter privileges to make it apply. If the extension is later upgraded
from0.7 to0.8+, the functions retain their exact fallback until a subsequent
release installs iterative settings; an extension upgrade alone does not
reconfigure them. Do not edit migration history to enable that optimization.

1. Record the database identity and inventory with the0.6.22 operator CLI:
   `rag service --config SERVER_CONFIG inventory --source-version 0.6.21 --identities --output BEFORE_JSON`.
   Resolve `SERVER_CONFIG`, `BEFORE_JSON` and the following dump paths for the
   intended installation. Use new private paths; never overwrite recovery proof.
2. Pause capture/mining and other writers using the installation's service
   procedure; retain their spools and queued work. Keep readers available if
   their connection budget permits function replacement. Lock acquisition can
   wait behind existing transactions; there is no measured production lock-time
   bound. Monitor the upgrade and the installation's normal lock budget. If it
   must be cancelled, retain the failed attempt and check the schema before retry.
3. Run `PGOPTIONS='-c search_path=public' rag service --config SERVER_CONFIG upgrade --source-version 0.6.21 --dump BEFORE_DUMP --apply --writers-stopped`.
   For a restricted owner, append `--verification-template TEMPLATE` using the
   prepared template described above. Require `restore_verified` and
   `original_rows_unchanged`, with exactly `034_lexical_eligibility_work.sql` and
   `035_document_permission_initplans.sql` applied, in that order. The command verifies its backup by
   independent restore before changing the database. A failed apply rolls back;
   inspect the error and schema inventory, then retry once with a fresh dump
   path after correcting the cause. If the retry fails, keep writers paused and
   escalate with both attempt records; do not reset migration markers. A
   successful repeat applies no migrations.
4. Start the0.6.22 services and adapters, resume writers, and check authenticated
   scoped search, client capture/replay and queued extraction progress. Create
   a target backup with `rag service --config SERVER_CONFIG verified-backup --source-version 0.6.22 --output AFTER_DUMP`.
   For a restricted owner, append `--verification-template TEMPLATE` here too.
   Require its independent restore to succeed before retiring the old runtime.

The source-write helper reuses its execution plan, while checking current
permissions and every dependent document on each call. Its owner, grants and
fixed search path remain unchanged. The populated rehearsal also checks scoped
source permission changes on a reused connection after the upgrade and after
restoring the target under a non-superuser owner. The bounded diagnostic and
characterization results are in [source-permission plan reuse](../benchmarks/2026-11-01-lexical-eligibility/source-permission-plan-reuse.json);
they do not establish the 40-client latency target.

The populated rehearsal is `tests/service/test_lexical_upgrade.py`: genuine
archived0.6.21 creates the store, an injected interruption rolls back034/035, retry
preserves originals and function privileges, the old scoped reader still returns
identical responses, and both source and target backups restore independently.

Restart all0.6.22 API processes for the scoped thematic selection repair as well;
it changes only the reader query, with no stored cache, knowledge or pending-job
rewrite. Existing0.6.21 readers retain their previous results and query costs.
Service workers must also restart on0.6.22: embedding preparation retains the
worker context on the calling thread, including foreground admission, single-input
pages and the10-second background HTTP timeout. Existing queued inputs and accepted
batches replay through the normal worker; no requeue, data rewrite or cache reset
is required. Unscoped local calls retain bounded two-thread execution; both
central and standalone fenced workers prepare serially on their calling thread.
Inspect the installed Ollama override as well: the former example's1536MiB
`MemoryHigh` can continuously throttle the actual model below its working set.
The0.6.22 example uses2GiB for both `MemoryHigh` and the unchanged `MemoryMax`.
Compare cgroup `memory.events`/pressure and a bounded embedding probe before
resuming extraction. If a budget change is necessary, retain the old override,
apply the measured values and restart the model service during the installation's
authorized maintenance window; then repeat the probe and check accepted-batch
replay. A repeated timeout or OOM blocks resumption: retain the queue and spools,
restore the previous override if needed and investigate sizing. The rehearsal
changed only an owned model instance, leaving the production override untouched.
Run the bounded probe from the prepared0.6.22 environment while extraction is
paused. Replace `SERVER_CONFIG` with that installation's private config path.
This sends one3,200-character synthetic input to the configured loopback model;
it does not access stored content or write to the database.

```sh
timeout 15s .venv/bin/python - SERVER_CONFIG <<'PYPROBE'
from pathlib import Path
import sys, time
from urllib.parse import urlsplit
import httpx
from agentic_rag.config import load_config
from agentic_rag.providers import validate_vectors
cfg = load_config(Path(sys.argv[1]))
endpoint = urlsplit(cfg.ollama_url)
if endpoint.hostname not in ('localhost', '127.0.0.1', '::1'):
    raise SystemExit('probe requires the intended loopback model endpoint')
started = time.monotonic()
try:
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        response = client.post(cfg.ollama_url + '/api/embed', json={
            'model': cfg.embed_model,
            'input': [('Synthetic upgrade probe. ' * 134)[:3200]],
        })
        response.raise_for_status()
        vectors = validate_vectors(response.json()['embeddings'], 1, cfg.embed_dim)
    elapsed = time.monotonic() - started
    if elapsed >= 10.0:
        raise ValueError('deadline exceeded')
except Exception:
    raise SystemExit('probe failed; keep extraction paused and inspect model sizing') from None
print({'vectors': len(vectors), 'dimension': cfg.embed_dim, 'seconds': round(elapsed, 3)})
PYPROBE
```

Require exit0, one vector of the configured dimension in less than10seconds,
and no new cgroup OOM or hard-limit events between the before/after samples.
The outer15-second deadline also bounds a stalled client. A successful probe is
one sizing check, not a sustained-load or latency-SLA acceptance.

Production service restarts and cross-host routing require their own rollout checks.

For code recovery keep schema035 and the verified0.6.22 backup tooling;
0.6.21 readers remain compatible. Do not remove a migration marker or replace
functions outside the bounded035 recovery below. To restore pre-upgrade state, follow the verified restore
and explicit database cutover in the
[source-evidence recovery procedure](system/rag-063-source-evidence-upgrade.md).
That snapshot excludes later writes; stop writers and account for retained
spools before cutover. No lossless downgrade after new writes is implied.

### Recovery from a document-policy plan regression

Use this path only after the verified0.6.21→0.6.22 upgrade has completed and
investigation has isolated a plan regression to035. It restores the exact021
document policy expressions, retaining034 and every original, history row and
queued job. It does not downgrade the schema or remove migration markers.

1. Arrange an authorized full maintenance window for this recovery. Unlike the
   ordinary upgrade above, stop API/dashboard access, workers, capture/mining,
   local MCP processes and other clients before recording the baseline. Reader
   requests also write traces and dashboard presence; they cannot remain active
   during the full table-hash comparison. Keep PostgreSQL available for the
   operator commands only. Use the installation's registered unit names and
   shutdown procedure; if this window is not authorized, stop here. Confirm all
   application sessions have drained using the owner connection:

   ```sh
   psql -X -v ON_ERROR_STOP=1 "service=DB_SERVICE" -c "SELECT pid,usename,application_name,state FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid()"
   ```

   Require zero other client backends and keep application endpoints stopped
   until every after-check completes. Resolve `DB_SERVICE` as in step2 before
   running this check. Select controls with this read-only operator query; it
   reports metadata only, never document contents:

   ```sh
   .venv/bin/python - SERVER_CONFIG <<'PY035CONTROLS'
   import json, sys
   from pathlib import Path
   from agentic_rag import db
   from agentic_rag.config import load_config
   with db.connect(load_config(Path(sys.argv[1]))) as conn:
       rows = conn.execute("""SELECT d.id allowed_id,d.domain,d.project_scope,f.id foreign_id,f.domain foreign_domain
           FROM documents d CROSS JOIN LATERAL
             (SELECT id,domain FROM documents WHERE domain<>d.domain ORDER BY id LIMIT 1) f
           WHERE d.project_scope IN ('global','unknown')
             AND NOT EXISTS(SELECT 1 FROM claim_records WHERE document_id=d.id)
             AND NOT EXISTS(SELECT 1 FROM fact_assertions WHERE document_id=d.id)
           ORDER BY d.id LIMIT 20""").fetchall()
       if not rows:
           raise SystemExit('no suitable controls: stop before policy change; rehearse on a copy')
       print(json.dumps(rows,default=str))
   PY035CONTROLS
   ```

   Choose one returned pair as `ALLOWED_ID`/`FOREIGN_ID` and run step3's scoped
   probe now, before changing policy. Require all three PASS lines. A control
   selection or baseline-probe failure means **preflight blocked**: do not alter
   policy or restore a backup; retain the error and resolve the inputs with the
   maintainer. If no changes were made, end the maintenance window through the
   installation's normal restart procedure. After successful preflight, keep
   all application processes stopped. Use new private paths for `RECOVERY_BEFORE`,
   `RECOVERY_AFTER` and `RECOVERY_DUMP`. Record and independently verify the
   current state before changing policy:

   ```sh
   rag service --config SERVER_CONFIG inventory --source-version 0.6.22 --identities --output RECOVERY_BEFORE
   rag service --config SERVER_CONFIG verified-backup --source-version 0.6.22 --output RECOVERY_DUMP
   ```

   For a restricted owner, append `--verification-template TEMPLATE` to the
   backup command. Require exit0 and successful independent restore. If either
   command fails, preserve the error, keep writers paused and stop here.
2. Resolve `DB_SERVICE` to the installation's owner-accessible libpq service
   entry for this database. Confirm identity with
   `psql -X "service=DB_SERVICE" -c 'SELECT current_database(),current_user'`.
   Policy replacement takes a table lock: use the installation's approved
   lock-wait budget and monitor existing readers as in upgrade step2. Run this
   non-interactive transaction; any SQL failure aborts the script and rollback
   occurs when its connection closes:

   ```sh
   psql -X -v ON_ERROR_STOP=1 "service=DB_SERVICE" <<'SQL035ROLLBACK'
   BEGIN;
   SET LOCAL search_path = pg_catalog, public;
   ALTER POLICY service_documents ON public.documents
     USING (public.rag_service_document(domain,project_scope))
     WITH CHECK (public.rag_service_document(domain,project_scope,true));
   DROP FUNCTION public.rag_service_permission(text,jsonb);
   COMMIT;
   SQL035ROLLBACK
   ```

   On failure, keep writers paused and follow **Recovery check failure** below.
3. Record the resulting inventory, require marker035 and unchanged application
   table hashes, then run the scoped probe below:

   ```sh
   rag service --config SERVER_CONFIG inventory --source-version 0.6.22 --identities --output RECOVERY_AFTER
   .venv/bin/python - RECOVERY_BEFORE RECOVERY_AFTER <<'PY035INVENTORY'
   import json, sys
   before, after = [json.load(open(p)) for p in sys.argv[1:]]
   assert before['identity'] == after['identity'], 'wrong database'
   assert '035_document_permission_initplans.sql' in after['migrations'], 'marker035 missing'
   assert before['migrations'] == after['migrations'], 'migration ledger changed'
   assert before['tables'] == after['tables'], 'application rows changed'
   print('inventory: PASS; marker035 and application rows preserved')
   PY035INVENTORY
   ```

   Resolve `ALLOWED_ID` to an existing ordinary document (no claim/assertion)
   in `global` or `unknown` scope, and `FOREIGN_ID` to an existing document in
   another domain. Use the pair selected and validated in step1;
   do not use an absent UUID as the negative control. The following local
   operator probe binds real reader/writer/admin database roles to the allowed
   domain and the two scopes `global`/`unknown`. It tests database policy, not
   API credential enrollment. Reader write denial tests its GRANT; the existing
   SQL035 role matrix separately proves negative RLS write checks. All writes use
   the audited gateway and are
   rolled back, including audit rows; no provider is called. It needs the same
   role login configuration as the installed service. If suitable documents
   are absent, stop and rehearse with approved synthetic fixtures on a copy;
   do not invent a passing control or add fixtures to production.

   ```sh
   .venv/bin/python - SERVER_CONFIG ALLOWED_ID FOREIGN_ID <<'PY035SCOPED'
   import sys
   from pathlib import Path
   import psycopg
   from agentic_rag import db, store
   from agentic_rag.config import load_config
   from agentic_rag.service.auth import Principal
   from agentic_rag.service.context import RequestScope, apply_connection
   cfg = load_config(Path(sys.argv[1]))
   allowed, foreign = sys.argv[2:]
   with db.connect(cfg) as owner:
       original = owner.execute('SELECT domain,project_scope FROM documents WHERE id=%s', (allowed,)).fetchone()
       other = owner.execute('SELECT domain FROM documents WHERE id=%s', (foreign,)).fetchone()
       assert original and other and original['domain'] != other['domain'], 'invalid controls'
       assert original['project_scope'] in ('global', 'unknown'), 'unsupported probe scope'
       assert not owner.execute('SELECT 1 FROM claim_records WHERE document_id=%s UNION ALL SELECT 1 FROM fact_assertions WHERE document_id=%s', (allowed, allowed)).fetchone(), 'ordinary document required'
   domain = frozenset({original['domain']})
   scopes = frozenset({'global', 'unknown'})
   target = 'unknown' if original['project_scope'] == 'global' else 'global'
   for role in ('reader', 'writer', 'admin'):
       principal = Principal('policy-recovery', 'operator', 'probe', domain, domain, scopes, scopes)
       with db.connect(cfg, role=role) as conn:
           apply_connection(conn, RequestScope(principal, cfg, role == 'reader'))
           try:
               assert conn.execute('SELECT id FROM documents WHERE id=%s', (allowed,)).fetchone(), 'allowed read denied'
               assert conn.execute('SELECT id FROM documents WHERE id=%s', (foreign,)).fetchone() is None, 'foreign read leaked'
               try:
                   changed = store.set_project_scope(conn, allowed, scope=target,
                       expected_scope=original['project_scope'], actor='policy-recovery', commit=False)
               except psycopg.errors.InsufficientPrivilege:
                   assert role == 'reader', 'permitted write denied'
               else:
                   assert role != 'reader' and changed, 'unexpected write result'
                   assert conn.execute('SELECT project_scope FROM documents WHERE id=%s', (allowed,)).fetchone()['project_scope'] == target
           finally:
               conn.rollback()
       print(role + ': allowed read, foreign denial and write permission PASS; rolled back')
   with db.connect(cfg) as owner:
       assert owner.execute('SELECT domain,project_scope FROM documents WHERE id=%s', (allowed,)).fetchone() == original
   PY035SCOPED
   ```

   Require exit0 from both scripts and all three role PASS lines. Capture a new
   inventory after the probe and repeat the table-hash comparison to prove that
   no gateway or audit write persisted. Resume writers only after all checks
   pass; otherwise follow **Recovery check failure**. Preserve inventories and
   backup. Compatible0.6.21 readers still work; this restores previous query
   costs, not a latency guarantee.
4. Re-enable035 only after the cause is resolved and the exact release SQL has
   passed the populated rehearsal. Repeat the full maintenance and preflight
   sequence in step1, keeping readers and writers stopped. Repeat step1 with new
   inventory/dump paths; this new verified backup is the **pre-reapply backup**.
   Set `RELEASE_ROOT` to the retained0.6.22 release directory. The explicit
   search path below prevents apply-time function shadowing; use it for the
   initial upgrade as well when the owner has a customized search path.

   ```sh
   PGOPTIONS='-c search_path=pg_catalog,public' psql -X -v ON_ERROR_STOP=1 --single-transaction "service=DB_SERVICE" --file RELEASE_ROOT/sql/035_document_permission_initplans.sql
   ```

   Repeat all step3 checks against the pre-reapply inventory before resuming
   writers. Ordinary `upgrade --apply` keeps marker035 and will not reapply it.
   SQL failure leaves the previous expressions intact. Any failed check takes
   the failure branch below, even if the SQL command itself exited0.

**Recovery check failure:** Keep all application endpoints, readers, capture,
mining and other writers stopped. If SQL failed atomically before commit and the
before/after inventory and scoped checks still pass, no restore is needed:
retain the failure and ask the maintainer whether to end maintenance in the
unchanged state. Do not retry without resolving the cause. The restoration
branch below applies to failed checks after commit or an uncertain state.
Retain the failing command/output, before/after inventories, verified backup
manifest, exact release revision and policy SQL. Do not delete marker035,
retry blindly or resume because only the migration command succeeded. Escalate
these artifacts to the installation maintainer. After rollback failure, the
recovery source is step1's `RECOVERY_DUMP`; after reapply failure it is the new
pre-reapply backup from step4. Restore that specific verified backup into a
separate target using the linked source-evidence recovery procedure's verified
restore and cutover flow. That procedure's historical0.6.15 source label does
not apply here: keep0.6.22 tooling, set `--source-version 0.6.22`, use this
step's verified0.6.22 backup, and require schema035 in the target inventory.
Do not replay source-origin quarantine or downgrade schema. Validate
its inventory and scoped checks, then obtain the normal explicit database
cutover authorization. Do not overwrite the current database. If the restored
copy also fails, leave writers paused and escalate without cutover. Retained
spools and any writes that escaped the pause must be reconciled before cutover;
no lossless recovery is claimed for such writes.

Permissions are bound on first evaluation within each statement/portal. Close
an open cursor before changing its binding and start a new statement; rebinding
mid-FETCH is unsupported. The service's `apply_connection` commits before reuse,
which closes ordinary portals. This is not a cross-statement permission cache.

The populated upgrade rehearsal exercises this rollback and explicit reapply,
including an owner without superuser privileges and an independently restored
target. No production execution or40-client performance pass is implied.

## Optional background embedding daemon

Use this section only when a0.6.22 central server should run its extraction
embeddings on a second, CPU-limited Ollama daemon (Issue92 A2). It is optional;
an installation without the keys keeps one daemon, one shared model lock and the
10-second background deadline. Do not use it for standalone stores, clients or
[managed embedding profiles](../provider-indexes.md), which keep their own route.
The settings and their validation are in the
[configuration reference](../06-configuration-reference.md#ollama).

Before starting, check all of these:

- All API and worker processes already run0.6.22 with the lane keys unset, and
  the lexical upgrade above has completed with both verified backups.
- An authorized maintenance window covers a model-service start and restarts of
  every API and worker process. Activation is not authorized by this document.
- The host has the memory for a second model copy. The reference measurement
  (4 vCPU, 8 GiB) used these limits; size other hosts from their own measurements.

| Daemon | Address | systemd limits | Ollama environment |
|---|---|---|---|
| Primary (unchanged role) | `127.0.0.1:11434` | `CPUQuota=350%`, `MemoryHigh=2G`, `MemoryMax=2G` | `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1` |
| Background | `127.0.0.1:11436` | `CPUQuota=100%`, `CPUWeight=1`, `MemoryHigh=2G`, `MemoryMax=2G`, `ReadOnlyPaths=MODEL_STORE` | `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NOPRUNE=1`, `OLLAMA_MODELS=MODEL_STORE` |

`MODEL_STORE` is the primary daemon's existing model directory; resolve it from
the installed primary unit. The background daemon only reads those files and
never pulls or prunes. Every lane call has a finite deadline of
`background_timeout_seconds` (60 s in the reference). The reference threads are
`num_thread = 2` for the primary and `background_num_thread = 1` for the lane.

### L0: pause extraction and check the host

The commands below use `ollama.service`, `agentic-rag-api.service` and
`agentic-rag-worker.service` from the deployment examples. If the installation
uses other unit names, record the mapping before executing any command. Use
`agentic-rag-ollama-background.service` for the new daemon. Keep its
`127.0.0.1:11436` listener private; first require no output from
`ss -ltn 'sport = :11436' -H`.
Configuration rejects an identical URL string, but does not resolve aliases
such as `localhost` and `127.0.0.1`. Step 5 checks the actual listeners.

**Leaving setup early (L0/L1):** do not leave extraction stopped after an
aborted setup. If the server configuration and verified primary model are
unchanged, stop the new background unit if it was started, then run
`sudo systemctl start agentic-rag-worker.service` and require
`systemctl is-active agentic-rag-worker.service` to report `active`. The lane
keys are still unset, so extraction uses the original primary path. If keys
have already been added, use L3 rollback first. If the primary model or binary
has changed and has not passed the required checks, keep extraction paused,
record that outage explicitly and restore a verified primary installation
before resuming. Every setup failure below returns through this path.

1. Stop extraction in the authorized window with
   `sudo systemctl stop agentic-rag-worker.service`. Require
   `systemctl is-active agentic-rag-worker.service` to report `inactive`.
   Wait for the current job to finish; never force-kill it. Queued windows,
   accepted batches and client spools remain available.
2. Check the primary with
   `systemctl show ollama.service -p CPUQuotaPerSecUSec -p MemoryHigh -p MemoryMax`.
   The table describes the reference configuration, not values installed by
   this procedure: require a3.5s quota (`CPUQuotaPerSecUSec=3.500000s`
   in `systemctl show` output) and both memory values
   `2147483648` for that reference. If they differ, keep the lane off and
   arrange a separately authorized primary-unit change and restart; leave
   setup through the early-exit path above. Step 5 loads the primary model
   with a synthetic input before requiring at least4GiB `MemAvailable`;
   this is an actual-state admission floor, not a guarantee for arbitrary
   future inputs. Keep the database and API running during the check. A
   different model or host needs its own sizing evidence.
3. Resolve the four unit inputs from the running primary using this read-only
   command. It prints only the selected paths and account names. Require a
   non-root primary account, an existing model directory readable by that
   account, and the same Ollama binary for both daemons. If discovery fails,
   leave through the early-exit path and resolve the installation before
   attempting setup again.

```sh
sudo python3 - <<'PYMODELUNIT'
import grp, json, pwd, re, subprocess
from pathlib import Path
pid = int(subprocess.check_output(
    ['systemctl', 'show', 'ollama.service', '-p', 'MainPID', '--value'], text=True))
if pid <= 0:
    raise SystemExit('primary daemon is not running')
proc = Path('/proc') / str(pid)
env = dict(item.split('=', 1) for item in (proc / 'environ').read_bytes().decode().split('\0')
           if '=' in item)
account = pwd.getpwuid(proc.stat().st_uid)
if account.pw_uid == 0:
    raise SystemExit('use a reviewed non-root model account before enabling the lane')
home = Path(env.get('HOME', account.pw_dir))
store = Path(env.get('OLLAMA_MODELS', str(home / '.ollama' / 'models'))).resolve(strict=True)
if not store.is_dir():
    raise SystemExit('model store is not a directory')
binary = str((proc / 'exe').resolve(strict=True))
if any(not re.fullmatch(r'[A-Za-z0-9_./-]+', value) for value in (str(store), binary)):
    raise SystemExit('paths need a separately reviewed systemd escaping rule')
print(json.dumps({'MODEL_USER': account.pw_name,
                  'MODEL_GROUP': grp.getgrgid(proc.stat().st_gid).gr_name,
                  'MODEL_STORE': str(store),
                  'OLLAMA_BIN': binary}, indent=2))
PYMODELUNIT
```

The worker is stopped, the primary is running and all four unit inputs are
known. Record the primary unit settings now and the loaded-model memory sample
from L1 step 5 with the rehearsal.

### L1: start and verify the background daemon

4. Copy [the background unit template](../../deploy/central-service/ollama-background.service.example)
   to an owned staging file named `agentic-rag-ollama-background.service`.
   Replace `MODEL_USER`, `MODEL_GROUP`, `MODEL_STORE` and `OLLAMA_BIN` with the
   L0 output; verify read access with
   `sudo -u MODEL_USER test -r MODEL_STORE` after replacing those two inputs.
   Review the rendered file, then run
   `systemd-analyze verify ./agentic-rag-ollama-background.service`.
   On any error, use the early-exit path. Before installation, require
   `systemctl show agentic-rag-ollama-background.service -p LoadState --value`
   to report `not-found` and require the destination to be absent (including
   dangling symlinks). Otherwise stop and compare the existing unit and
   drop-ins; do not overwrite them. Install only the reviewed file with the
   same guards:

   ```sh
   test "$(systemctl show agentic-rag-ollama-background.service -p LoadState --value)" = not-found &&
     test ! -e /etc/systemd/system/agentic-rag-ollama-background.service &&
     test ! -L /etc/systemd/system/agentic-rag-ollama-background.service &&
     sudo install -m 0644 ./agentic-rag-ollama-background.service /etc/systemd/system/agentic-rag-ollama-background.service
   ```

   Require exit0, then run `sudo systemctl daemon-reload`. An unsuccessful
   install returns through the early-exit path.
5. In the authorized maintenance window, keep extraction paused and wait for
   foreground inference to finish. Keep the database and API running. Save
   the following block as an owned staging file `lane-memory-check.py`.
   It is specific to the pinned reference model and thread settings; a
   different model needs a separately reviewed reference vector and sizing.
   `SERVER_CONFIG` is the private configuration; `PG_UNIT` is the actual
   running PostgreSQL unit recorded for this installation.

   The command unloads the primary model through Ollama, checks that its
   runner has exited without restarting the daemon, then warms it with the
   configured two-thread option. It does not change stored vectors or jobs.
   A cold model load is part of this maintenance step. Do not run it while
   serving foreground inference, during a load phase or while draining work.

   ```python
   # lane-memory-check.py: run with the prepared 0.6.22 Python environment.
   import hashlib, struct, subprocess, sys, time
   from datetime import datetime
   from pathlib import Path
   import httpx
   from agentic_rag.config import load_config
   from agentic_rag.providers import validate_vectors

   cfg = load_config(Path(sys.argv[1]))
   primary, pg, mode = sys.argv[2:5]
   background = 'agentic-rag-ollama-background.service'
   worker, api = 'agentic-rag-worker.service', 'agentic-rag-api.service'
   # Replace the three example API/worker/background names if L0 mapped them.
   if mode not in {'before-background', 'before-load'}:
       raise SystemExit('mode must be before-background or before-load')
   def prop(unit, name):
       return subprocess.check_output(
           ['systemctl', 'show', unit, '-p', name, '--value'], text=True).strip()
   def active(unit):
       return prop(unit, 'ActiveState') == 'active'
   if active(worker) or not active(pg) or not active(api):
       raise SystemExit('require worker paused and database/API running')
   if active(background) != (mode == 'before-load'):
       raise SystemExit('background state does not match this maintenance point')
   if cfg.embed_model not in {'bge-m3-q8', 'bge-m3-q8:latest'} or cfg.embed_dim != 1024:
       raise SystemExit('a different model needs its own reviewed sizing reference')
   tag = 'bge-m3-q8:latest'
   digest = '7f5f712dd874a537ca5cbbd6366cec74ebef63e364e102ec070836e8b7ed340d'
   reference = 'a430c659c9f04749a1e2ab16c268a2e967f86b525f5bbe842d04f1b7c789505b'
   def runners(unit):
       group = Path('/sys/fs/cgroup') / prop(unit, 'ControlGroup').lstrip('/')
       return sorted(int(pid) for pid in (group / 'cgroup.procs').read_text().split()
                     if (Path('/proc') / pid / 'comm').read_text().strip() == 'llama-server')
   def models(client, url):
       r = client.get(url + '/api/ps', timeout=5)
       r.raise_for_status()
       return r.json()['models']
   daemon = int(prop(primary, 'MainPID'))
   if daemon <= 0:
       raise SystemExit('primary daemon is not running')
   url = cfg.ollama_url.rstrip('/')
   with httpx.Client(trust_env=False) as client:
       r = client.post(url + '/api/embed', timeout=60,
                       json={'model': cfg.embed_model, 'input': [], 'keep_alive': 0})
       r.raise_for_status()
       deadline = time.monotonic() + 60
       while True:
           if not models(client, url) and not runners(primary):
               break
           if time.monotonic() >= deadline:
               raise SystemExit('primary runner did not unload; stop and retain evidence')
           time.sleep(0.5)
       if int(prop(primary, 'MainPID')) != daemon:
           raise SystemExit('primary daemon changed during maintenance')
       endpoints = [(primary, url, 2)]
       if mode == 'before-load':
           endpoints.append((background, 'http://127.0.0.1:11436', 1))
       for unit, endpoint, threads in endpoints:
           previous = None
           for _ in range(2):
               r = client.post(endpoint + '/api/embed', timeout=60,
                   json={'model': cfg.embed_model, 'input': ['Synthetic parity probe.'],
                         'options': {'num_thread': threads}, 'keep_alive': '10m'})
               r.raise_for_status()
               vector = validate_vectors(r.json()['embeddings'], 1, 1024)[0]
               actual = hashlib.sha256(b''.join(struct.pack('<d', v) for v in vector)).hexdigest()
               resident = models(client, endpoint)
               matching = [m for m in resident if m.get('name', m.get('model')) == tag
                           and m.get('digest') == digest]
               pids = runners(unit)
               if actual != reference or len(matching) != 1 or len(pids) != 1:
                   raise SystemExit('reference vector, model identity or runner mismatch')
               expiry = datetime.fromisoformat(matching[0]['expires_at'].replace('Z', '+00:00'))
               if expiry.timestamp() <= time.time() + 60 or (previous is not None and previous != pids):
                   raise SystemExit('resident model expired or runner changed')
               previous = pids
               print({'unit': unit, 'models': resident, 'runner_pids': pids})
   available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                        if line.startswith('MemAvailable:'))) * 1024
   minimum = (4 if mode == 'before-background' else 2) * 1024**3
   print({'mode': mode, 'MemAvailable': available, 'minimum': minimum})
   if available < minimum:
       raise SystemExit('CAPACITY_BLOCKED: retain evidence; do not lower the floor or retry adaptively')
   ```

   Run `sudo timeout 400s .venv/bin/python lane-memory-check.py SERVER_CONFIG ollama.service PG_UNIT before-background`.
   Require exit0 and at least4GiB `MemAvailable`, with the primary loaded and
   the database/API still active. Retain the output and a recursive cgroup
   memory inventory (including nested PostgreSQL and scope units). Record
   the production Ollama unit too if it differs from the measured primary;
   an on-demand model load is real host demand, not an excluded anomaly.
   If the check fails, use the early-exit path; do not stop other services,
   lower a threshold or repeat the same failed sizing attempt. After a delay
   or any new primary inference, repeat the declared maintenance check before
   starting the background daemon. Start only that daemon with
   `sudo systemctl start agentic-rag-ollama-background.service`. Require
   `curl -fsS http://127.0.0.1:11436/api/tags` to list the `[embed] model` tag.
   If it does not, run
   `sudo systemctl stop agentic-rag-ollama-background.service`, retain
   `journalctl -u agentic-rag-ollama-background.service` and use the early-exit
   path. After a successful start, run
   `sudo ss -ltnpH '( sport = :11434 or sport = :11436 )'` and
   `systemctl show ollama.service agentic-rag-ollama-background.service -p Id -p MainPID`.
   Require the listener PID at11434 to match the primary unit's `MainPID`,
   and the PID at11436 to match the background unit's different `MainPID`.
   Reject any alias or mapping that reaches the same process. Record these
   ports and use this exact background address as `LANE_URL` in step 6 and
   `background_url` in step 7. A failed mapping check uses the early-exit path.
6. Run the identity and parity probe from the prepared0.6.22 environment while
   extraction remains paused. `SERVER_CONFIG` is the private server configuration,
   `LANE_URL` the background address, and the two thread values are the planned
   `num_thread` and `background_num_thread` (`-` for unset). It sends only the
   three synthetic inputs below and writes nothing. Each input is embedded by
   the primary without thread option (as stored vectors and reuse caches were
   made), by the primary with `num_thread` and by the background daemon; all
   three vectors must be identical, because caches keep the primary identity.

```sh
timeout 400s .venv/bin/python - SERVER_CONFIG LANE_URL 2 1 <<'PYPARITY'
from pathlib import Path
import sys
import httpx
from agentic_rag.config import load_config
from agentic_rag.providers import validate_vectors
cfg = load_config(Path(sys.argv[1]))
lane = sys.argv[2].rstrip('/')
threads = [None if v == '-' else int(v) for v in sys.argv[3:5]]
tag = cfg.embed_model if ':' in cfg.embed_model else cfg.embed_model + ':latest'
inputs = ['Synthetic parity probe.', ('Synthetic upgrade probe. ' * 134)[:3200],
          'Kurzer synthetischer Text mit Umlauten: äöüß.']
def digest(client, url):
    found = {m['digest'] for m in client.get(url + '/api/tags', timeout=5).json()['models']
             if m.get('name', m.get('model')) == tag}
    if len(found) != 1:
        raise SystemExit('model tag missing or ambiguous')
    return found.pop()
def embed(client, url, text, thread):
    body = {'model': cfg.embed_model, 'input': [text]}
    if thread is not None:
        body['options'] = {'num_thread': thread}
    response = client.post(url + '/api/embed', json=body, timeout=60)
    response.raise_for_status()
    return validate_vectors(response.json()['embeddings'], 1, cfg.embed_dim)[0]
with httpx.Client(trust_env=False) as client:
    before = digest(client, cfg.ollama_url), digest(client, lane)
    # Stored vectors and reuse keys came from the unthreaded primary request.
    triples = [(embed(client, cfg.ollama_url, t, None), embed(client, cfg.ollama_url, t, threads[0]),
                embed(client, lane, t, threads[1])) for t in inputs]
    after = digest(client, cfg.ollama_url), digest(client, lane)
if len({*before, *after}) != 1:
    raise SystemExit('digests differ; do not enable the lane')
if any(not (a == b == c) for a, b, c in triples):
    raise SystemExit('vectors differ; do not enable the lane')
print({'digest': before[0], 'inputs': len(triples), 'identical': True})
PYPARITY
```

   Require exit0 and `identical: True`. Any other result keeps the lane off:
   stop the background unit, keep the evidence and use the early-exit path.
   This probe covers three
   synthetic inputs; it does not replace the complete-input parity gate of the
   acceptance run.

### L2: enable, restart and verify the route

7. Add `background_url`, `background_timeout_seconds`, `num_thread` and
   `background_num_thread` under `[ollama]` in the server configuration. Add
   `[service] request_consumers` only on hosts whose default pool allows it;
   the API refuses to start otherwise and names the allowed maximum. The
   reference values are `background_url = "http://127.0.0.1:11436"`, timeout60,
   primary threads2, background threads1 and `request_consumers = 4`.
8. Restart every API process (`sudo systemctl restart agentic-rag-api.service`
   for the example installation). Keep the worker paused. After the parity
   probe and all setup or rollback inputs, run
   `sudo timeout 400s .venv/bin/python lane-memory-check.py SERVER_CONFIG ollama.service PG_UNIT before-load`.
   Require exit0: both models must be resident with stable runner PIDs and
   their reference vectors, with at least2GiB `MemAvailable`. Do not unload
   the background model or erase its long-input workspace history. A failure
   uses L3; do not start extraction or a load measurement. Then run
   `sudo systemctl start agentic-rag-worker.service`. All processes read the file
   only at start; a mix of old and new settings still obeys the single worker
   lock and execution pins, but restart them together to avoid it.
9. Verify for up to five minutes: the `pending` count from `rag service --config SERVER_CONFIG status`
   falls over time, the background daemon's journal shows embed requests, and
   this read-only query as the database owner returns no rows (`DB` is the
   `[db] name`):
   `psql -d DB -c "SELECT result->>'code' code, count(*) FROM service_windows WHERE state='blocked' AND result->>'code' LIKE 'background_model_%' GROUP BY 1"`.
   Scoped search and context requests keep working while extraction runs.
   If background errors persist, pending work makes no progress despite no
   foreground demand, an OOM event appears, or host `MemAvailable` falls below
   2GiB, stop the worker and follow L3. Retain status, daemon journals and
   before/after cgroup `memory.events`; do not delete jobs to clear an error.

### L3: recovery and rollback

**Safety precondition for every worker start below:** the primary model and
binary must still be the verified installation, or have completed the required
post-update checks. Removing lane keys does not verify a changed primary.
If that condition is false, leave the worker stopped, retain the recorded
outage and restore the verified primary before executing any worker-start
command. This precondition also applies when an update's parity probe fails.

- A window that reports `background_model_unavailable` (inference timeout or
  outage) or `background_model_identity` (digest unavailable, digest change or
  invalid vectors) is still
  pending. Nothing was stored for it, its attempt was not used up and its
  accepted extraction is replayed without a second provider call. Restore the
  daemon or digest. Before restarting a stopped background daemon, keep
  the worker paused, repeat L1 step 5 (`before-background`,4GiB), then start
  only the background daemon and check its listener mapping. Before every
  resumed worker start after that recovery, run the step 8 `before-load`
  check (both resident,2GiB). Do not perform these resets during normal
  foreground traffic or an active acceptance load. If step 9 stopped the
  worker, explicitly run
  `sudo systemctl start agentic-rag-worker.service` and require
  `systemctl is-active agentic-rag-worker.service` to report `active`.
  A running worker retries the retained window after its backoff.
  An unreachable daemon during a tag lookup also reports
  `background_model_identity`; check reachability before treating it as a
  changed model. If L1 cannot be restored, use the rollback below.
- To roll back, stop the worker, remove all four `[ollama]` lane and thread keys
  and `request_consumers` together (a background setting without
  `background_url` stops configuration loading), restart every API process
  with `sudo systemctl restart agentic-rag-api.service`, then run
  `sudo systemctl start agentic-rag-worker.service` and require
  `systemctl is-active agentic-rag-worker.service` to report `active`.
  Stop the background unit. Jobs, receipts, caches and
  knowledge are not deleted; work continues on the primary daemon.

The fixed reset points release workspace left by setup, parity checks,
seed generation and the temporary single-lane rollback. The acceptance
workload's foreground queries are at most73 characters. The measured memory
and latency result applies only to that workload: production queries are not
length-limited, and longer requests can grow the runner again. A sizing check
is not a guarantee for arbitrary request lengths or uninterrupted maintenance.
Never reset a model to conceal pressure during load or backlog drain.

Before a model pull, model-tag replacement or Ollama binary upgrade, stop the
worker as in L0 and stop `agentic-rag-ollama-background.service`. Preserve a
verified copy of the current Ollama binary, model-tag manifest and every blob
it references, together with their SHA-256 values and the primary unit file.
Keep that recovery copy outside the active model store so a pull or prune cannot
remove it; verify that the retained manifest resolves to the saved blobs before
updating. Do not proceed without those recovery files. Perform the
separately authorized update through the primary installation, then restart
the primary daemon. Repeat L0 step 3 discovery and compare all four inputs
with `systemctl cat agentic-rag-ollama-background.service` and the saved
rendered unit. If any input differs, stage and verify a revised unit as in
L1 step 4; retain and compare the existing file before its separately reviewed
replacement. Restart the background daemon only after these inputs agree,
then repeat L1's parity probe before restarting extraction.
Require unchanged digests throughout that probe and `identical: True`; otherwise
keep extraction paused and follow L3's safety precondition: restore the verified
primary before a rollback can start the worker. Sharing a binary and model store
can change both digests together: matching digests alone do not renew the
parity evidence. Also repeat the complete-input acceptance gate when changing
thread options or the model/runtime used for an accepted load result. Keep the
old and new versions, digest, settings and probe output with the update record.

Client rollout note: clients from this release follow the server's
`retry_after` value. Every deployed queued server already sends `1`, so updated
clients poll about once per second, also against older servers. Before the
server acknowledges a request, a client resends the same request every0.3s
plus up to25% random delay on contention or timeouts, until its deadline.
The server's limits are unchanged: twelve control requests per second per
namespace and four control slots. Many waiting clients in one namespace
therefore see more `request_rate_limited` answers and may return a pending
handle at their deadline; that handle is not a result.

The real-component rehearsal of these success and recovery cases is
`tests/service/test_model_lane_runtime.py`, plus the A2 steps in the populated
upgrade test; the evidence is in the
[review record](evidence/agent-plugins.md#s06808-optional-model-lane-and-client-polling).
They use simulated model daemons; no physical-model or40-client result is
claimed here.

## Completion and maintenance

The operation completes when the host discovers the package, current knowledge
and compaction continuation work within its authenticated scope, accepted input
survives restart/replay and the applicable native observation is recorded.
Disable the owned test installation after rehearsal. Retain knowledge, pending
sources/requests and recovery records. Reassess this playbook when host events,
plugin schema, request limits, authentication or spool ownership changes.

Sources: [runtime/limits/matrix](../14-agent-plugins.md),
[request engine](../../agentic_rag/service/requests.py),
[package operator](../../agentic_rag/plugins/package.py).
