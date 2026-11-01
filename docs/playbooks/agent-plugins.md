---
title: Install or recover a native agentic-rag client
type: playbook
audience: administrators
version: 0.6.21
---

# PB06801: Install or recover a native agentic-rag client

## Identity and scope

- Class: system.
- Origin: Issue #68, FR01–09 in [the specification](../specs/6-10-agent-plugins/spec.md).
- Owner/audience: deployment administrator; agent user for status/cancel recovery.
- Target: 0.6.21/schema033; inherited plugin protocol024, owned plugin directories and an explicitly enrolled client.
- Readiness deadline: before activating a new client or upgrading a central server.
- Last edited: 2026-11-01 (procedures independently reviewed; final delivery/performance gates remain open).
- Evidence: [review and rehearsal record](evidence/agent-plugins.md).

## When to use / when not to use

Use for packaging an existing Python installation, staged client/server updates,
or a tool that reports a waiting handle. Do not use it to import independent
stores, merge department permissions or cut over production writers. Those actions
retain the [6.0 deployment/upgrade gates](../verification/issue58-service.md).
An unavailable native model login blocks claims about that host's interactive UI;
it does not justify copying another department's credentials.

## Before starting

1. Choose an existing Python environment with agentic-rag0.6.21 and run
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
