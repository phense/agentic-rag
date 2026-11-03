---
id: PB07101
title: Record and evaluate scoped retrieval feedback
type: task
doc_id: retrieval-feedback
readers: [authorized-writer, local-operator]
status: drafted
version: 0.6.28
depends_on: [central-service, private-confirmed-corrections]
assets: []
last_reviewed: 2026-11-03 (independent whole-content review; correction recheck pending)
summary: Capture an explicit search, revise its usefulness signal and privately evaluate an operator-approved failure.
---

# PB07101: Record and evaluate scoped retrieval feedback

## Identity and scope

- Class: system playbook.
- Origin: [Issue71](https://github.com/phense/agentic-rag/issues/71),
  [AC-001–009](specs/RAG-071-scoped-retrieval-feedback/spec.md).
- Audience: authorized writers; a local database operator approves and exports cases.
- Owner: repository maintainer and the operator of the selected installation.
- Target: 0.6.28/schema037, upgraded from 0.6.27/schema036.
- Readiness deadline: before first feedback enablement.
- Last edited: 2026-11-03.
- Review, measured examples and rehearsal: [verification record](verification/retrieval-feedback.md).

Use this procedure when a person or authorized client wants to report a particular
search result. Ordinary search does not create feedback records. Feedback changes
neither source trust, claim review, factual validity nor ranking. A useful result
may still be wrong; a missing result may reflect an incomplete query.

The initial release captures searches explicitly. It has no dashboard voting
button or automatic training. Capture and mutation are off by default. Existing
feedback remains inspectable after disabling the feature, subject to current access.
New operator approvals also require enablement; retained current approvals can
still be exported and evaluated while capture is disabled.

Local private operations refuse an unexpectedly exposed approval registry
(`operator_private_registry_exposed`). Stop approval/export/evaluation and leave
feedback disabled until the database owner restores the installation's approved
owner-only access. Do not grant broader access to work around this refusal; keep
existing private exports protected. The migration strips unexpected default
grants from new feedback tables without changing existing table privileges.

## Terms

| Term | Meaning here |
|---|---|
| Event | Immutable metadata for one explicitly captured search. |
| Signal | A writer's typed feedback, including its revision and retained history. |
| Retry key | A UUID chosen once and reused for the same search or submission. |
| Feedback version | An opaque `fb1:` digest binding evidence and current memory text. |
| Approval | A local operator's permission to use a current negative signal for evaluation. |
| Source family | Connected original sources kept together in one evaluation split. |
| Held-out test | Cases whose source families stay separate from development cases. |

## Before starting

Use Bash and the intended installed executable. Select a domain and exact project
that the writer may read and write, or use `--scope global` instead of `--project`.
The examples use synthetic text; replace the selectors with your authorized ones.
Do not paste credentials or complete private prompts into shell history.

Define these installation parameters with absolute paths:

```sh
RAG=/absolute/path/to/0.6.28/.venv/bin/rag
CFG=/absolute/path/to/server-or-client.toml
DOMAIN=general
PROJECT=/absolute/path/to/project
export AGENTIC_RAG_CONFIG="$CFG"
"$RAG" feedback --help
```

For remote capture, `CFG` is an existing authenticated client configuration. For
approval/export/evaluation, use a separate local operator configuration with the
intended database; client mode, a request scope, a worker lease and read-only mode
are rejected. Keep that database owner's credentials on the server.

## A: Upgrade and enable deliberately

The upgrade adds four feedback tables and changes no existing knowledge or
vectors. It performs no image backfill, model inference or re-encoding. Before a
production operation, use the installation's approved maintenance procedure to
record and pause every writer, including hooks, MCP clients and the service
worker. Preserve its exact stop/start commands and prior running state. The
[central-service upgrade procedure](13-central-service.md#upgrade-the-local-store)
provides the deployment and quiescence checks.

1. With the 0.6.28 executable, inspect the selected installation:

   ```sh
   "$RAG" service --config "$CFG" preflight --source-version 0.6.27
   ```

   Require `ready: true` before proceeding. Preserve the result privately. Stop on
   an unsupported schema, wrong database identity or failed preflight.

2. After writers are paused, apply the migration with a new absolute dump path:

   ```sh
   DIR=/absolute/private/feedback-upgrade
   umask 077
   mkdir -p "$DIR"
   "$RAG" service --config "$CFG" upgrade --source-version 0.6.27 \
     --dump "$DIR/pre-feedback.dump" --apply --writers-stopped
   ```

   Require independently verified backup/restore and unchanged original rows.
   An existing dump is not overwritten: preserve it and use a new filename.
   For a deployment owner without extension-creation rights, first prepare the
   empty verification template described in
   [restore-verification privileges](15-dashboard.md#restore-verification-privileges),
   then add `--verification-template TEMPLATE` to `upgrade` and the
   `verified-backup` command in step A3 (not to `inventory`).
   The template requires `vector` in schema `public` and the documented preload.

3. Verify the upgraded store and preserve a target backup:

   ```sh
   "$RAG" service --config "$CFG" inventory --source-version 0.6.28 \
     --output "$DIR/post-feedback-inventory.json"
   "$RAG" service --config "$CFG" verified-backup --source-version 0.6.28 \
     --output "$DIR/with-feedback.dump"
   ```

   Require schema037 and `restore_verified: true`. If either check fails, keep
   writers paused and follow recovery R2 below. Otherwise start the reviewed
   0.6.28 runtime, reconnect clients, check health and resume only prior writers.

4. To enable capture, preserve the current server configuration and add or edit
   the existing section once:

   ```toml
   [feedback]
   enabled = true
   ```

   Restart the configured API and worker through the installation's maintenance
   procedure. Restart/reconnect local CLI/MCP clients as appropriate. A client
   configuration alone cannot enable a disabled server. Keep ordinary search
   working and perform B1 before inviting users.

A successful upgrade leaves existing knowledge unchanged, schema037 installed
and feedback disabled until step A4. If the first capture reports
`feedback_disabled`, check the configuration loaded by the serving process.

## B: Capture and revise one signal

Each command below prints JSON. Save the returned IDs and revision numbers;
never substitute a document ID for an event or signal ID.

1. Generate a search retry key and capture an explicit lexical search:

   ```sh
   SEARCH_KEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
   "$RAG" feedback search 'synthetic feedback example' --domain "$DOMAIN" \
     --project "$PROJECT" --strategy lexical --idempotency-key "$SEARCH_KEY"
   ```

   Expect `event.id`, ordinary `results` and `warnings`. A matching retry returns
   the same event, `results: []` and `feedback_replay_metadata_only`; bodies are
   not stored for replay. Reusing the key for different inputs is a conflict.
   A remote `pending`/`waiting` handle is not a captured event: retry the same
   command and key until it completes or investigate the service failure.

2. Submit one signal for `EVENT_ID`, using a new submission key:

   ```sh
   EVENT_ID=returned-event-uuid
   SIGNAL_KEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
   "$RAG" feedback submit "$EVENT_ID" --kind useful \
     --idempotency-key "$SIGNAL_KEY" --comment 'Useful for this lookup'
   ```

   Expect one signal ID at revision 1. Repeat with the same key and same inputs
   after a lost response. For a negative signal use `not_useful`, `wrong_source`
   or `missing_evidence`. `--result-id` must name a returned document;
   `--expected-id` must name a currently visible document. These are labels,
   not evidence review decisions.

3. Update the signal using its current revision, or inspect it before editing:

   ```sh
   SIGNAL_ID=returned-signal-uuid
   "$RAG" feedback get --feedback-id "$SIGNAL_ID"
   "$RAG" feedback update "$SIGNAL_ID" --expected-revision 1 --kind not_useful
   ```

   Expect revision 2. `feedback_conflict` means the inspected revision is stale;
   inspect again and decide whether the new state still needs an edit.

4. Retract the signal when it should no longer count:

   ```sh
   "$RAG" feedback retract "$SIGNAL_ID" --expected-revision 2
   "$RAG" feedback list --limit 20
   ```

   Expect `state: retracted`, revision 3 and preserved history. Retraction does not
   erase audit history. A changed or withdrawn reference is marked `stale`; a
   now-inaccessible reference is withheld. Do not change source permissions to
   recover another actor's feedback.

REST exposes the same authenticated tool names at
`POST /v1/tools/memory_feedback_search`, `memory_feedback_submit`,
`memory_feedback_update`, `memory_feedback_retract`, `memory_feedback_get` and
`memory_feedback_list`. JSON arguments use underscores, such as
`idempotency_key` and `expected_revision`. Existing protocol/authentication and
rate limits apply. The write-capable MCP server exposes all six tools; the
read-only server exposes only get/list. A read-only principal cannot submit.

## C: Approve and reproduce a failure privately

Only a local operator performs these steps. Switch to the intended local
operator configuration before C1:

```sh
OPERATOR_CFG=/absolute/path/to/local-operator.toml
export AGENTIC_RAG_CONFIG="$OPERATOR_CFG"
```

Select a current negative signal
with `expected_id`; confirm the expected document is relevant by reading its
original evidence. Approval does not change the document's review state.
Use a private working directory outside every Git repository. Exported queries
are private even after secret screening.

1. Inspect independent signals in one exact selector:

   ```sh
   "$RAG" feedback summary --domain "$DOMAIN" --project "$PROJECT" --limit 32
   ```

   Multiple machines and retries belonging to one authenticated user do not
   become independent votes for the same source family. Counts do not affect
   ranking. Stop if the selected actor or source does not match the case.

2. Enter the bounded query without a literal shell-history entry and approve
   the inspected signal revision:

   ```sh
   SIGNAL_ID=selected-current-negative-signal-uuid
   REVISION=current-inspected-revision
   IFS= read -r -s -p 'Original query (private): ' QUERY
   "$RAG" feedback approve "$SIGNAL_ID" --expected-revision "$REVISION" --query "$QUERY"
   unset QUERY
   ```

   The query must match the event's SHA256, contain at most 512 characters and
   pass secret screening. Use a trusted host: a running command's arguments may
   be visible to its operator. A changed signal, expected source or feedback
   version refuses approval; inspect the current state before a new decision.

3. Export current approvals to a new private file:

   ```sh
   PRIVATE=/absolute/private/retrieval-feedback
   umask 077
   mkdir -p "$PRIVATE"
   "$RAG" feedback export --domain "$DOMAIN" --project "$PROJECT" \
     --limit 32 --output "$PRIVATE/cases.json"
   ```

   Require file mode 0600 and parent mode 0700. Symlinks, Git paths, existing
   outputs and unsafe text are refused. Preserve withheld/stale counts; they
   are not successful reproductions. Changes to signal revision, retraction,
   expected evidence or captured references invalidate earlier approvals.

4. Run the existing private evaluator on the exported file:

   ```sh
   "$RAG" benchmark evaluate-corrections --input "$PRIVATE/cases.json" \
     --output "$PRIVATE/report.json"
   ```

   Inspect all baseline/current hit, miss and stale/withheld denominators by
   split. The separate `private-retrieval-feedback` format uses network-free
   lexical retrieval, changes no knowledge and does not tune or activate a
   ranking profile. Keep connected source families wholly in one split.
   A lexical reproduction is not a claim about an earlier hybrid/model path.

The expected result is an explicit account of reproduced and unreproduced
failures, with stale cases withheld. A successful process exit alone does not
establish a retrieval-quality gain. Store exports and reports under the local
retention policy; never commit them or send them to a provider automatically.

## Limits and retained information

| Boundary | Initial limit |
|---|---:|
| Event snapshot | 20 results; 16 source versions per result; 64 KiB |
| Capture | k 1–20; nonempty query at most 10000 characters |
| Signal comment | 1000 characters, secret-stripped before storage |
| Signal history | 32 revisions including retraction |
| Namespace storage | 1024 events, 2048 signals; 16 MiB conservative accounting |
| Namespace mutations | 120/hour, including capture and updates |
| Private approval/export | Query 512 characters; 32 cases; private file up to 8 MiB |

Accounting remains effective after permissions change and can refuse before
actual JSON reaches 16 MiB. Caps refuse explicitly; there is no silent expiry of
acknowledged feedback or supported automatic pruning in this release.

Events retain query hashes, settings and bounded IDs/version snapshots, not raw
queries, titles, bodies or snippets. Feedback `fb1:` versions also cover plain
legacy memory text; canonical `ev1:` evidence tokens remain unchanged. Lexical
capture records models as unused; optional vector paths may record only
configured identity when a pinned model identity is unavailable. A local approval
retains the reconstructed query in an owner-only table. Existing durable service
request receipts retain their usual short-lived arguments/results for 300 seconds;
feedback does not remove that existing retention. Use the existing trace-redaction
and access rules for operational diagnostics.

## Interruption, recovery and rollback

| Path | Condition and action | Expected result / stop condition |
|---|---|---|
| R1 | Lost search/submission response: retry exactly the same inputs and key. | One retained event/signal; conflicting inputs refuse. Never invent a replacement success. |
| R2 | Upgrade failed: preserve dump/manifest and error, keep writers paused, inspect inventory using 0.6.28. An interrupted uncommitted037 may be retried after fixing the cause with a new dump filename. | Original store remains the authority; resume only after verified upgrade and scope/health checks. |
| R3 | Disable or roll back code: set `enabled=false`, use the preserved027 runtime and prior service launch configuration, then reconnect clients. | Ordinary0.6.27 readers work; all037 tables and feedback are retained. Old inventory/upgrade tooling refuses newer schema, so use 0.6.28 tooling for inspection/backup. |
| R4 | Corruption or failed post-upgrade checks: restore the verified pre-upgrade dump into a separate empty target using the commands below. | Require restore verification and original-row equality; keep the current store for reconciliation. No cutover until the maintainer accepts any writes lost since the dump. |
| R5 | Audit, quota or authorization failure: preserve the bounded error and own IDs. Correct authority/configuration or inspect limits before retrying. | No partial event/signal/usage commit. Do not relax quotas or restore revoked access to make a request pass. |

For R4, prepare a private `TARGET` configuration pointing at a new empty database
with the embedding identity recorded by the source manifest, then run 0.6.28 tooling:

```sh
TARGET=/absolute/path/to/recovery-target.toml
"$RAG" service --config "$TARGET" restore-target --dump "$DIR/pre-feedback.dump" \
  --manifest "$DIR/pre-feedback.dump.manifest.json" --apply
```

Require `restore_verified: true` and `original_rows_unchanged: true`; inspect
schema037 and the retained source rows before any cutover. This restores and
upgrades a copy, not a schema downgrade. A failed restore or scope/health check
keeps writers paused and both stores intact; escalate to the maintainer with the
private manifest and bounded errors. Never retry a restore into a nonempty target
without the supported `--resume` checks.

## Completion and maintenance

The operation is complete when the intended signal and revision are visible to
its owner, foreign access is denied, knowledge is unchanged and every exported
case has current explicit approval. Production enablement additionally requires
the upgrade/restore and scoped runtime checks. Disabling the feature preserves
all acknowledged feedback; rollback never drops schema037.

Recheck this playbook when tool schemas, versions, quota accounting, identity
rules, source eligibility, private-file guards or the evaluation format changes.
Update the [verification record](verification/retrieval-feedback.md) after an
actual rehearsal; drafting or a content review does not establish execution.
