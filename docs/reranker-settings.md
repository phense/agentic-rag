---
id: PB062-SETTINGS
title: Choose and upgrade local reranker settings
type: task
doc_id: standalone
readers: [operator]
status: reviewed
version: 0.6.15 / schema028
last_edited: 2026-10-30
depends_on: []
assets: []
summary: Prepare pinned local models, choose a server-wide preset and preserve existing knowledge during upgrade and recovery.
---

# Choose and upgrade local reranker settings

The dashboard's **Settings** page lets a service administrator choose the local
model that reorders ambiguous search results. mMARCO DE/EN is the default in
0.6.15. MiniLM L6 EN/DE and Jina tiny (English only) are the other presets.
A change affects subsequent server searches and survives a server restart.

PB062-SETTINGS is a system playbook owned by the deployment administrator,
originating in [Issue62](https://github.com/phense/agentic-rag/issues/62), settings
requirements AC001–008. Writing depth: medium standalone procedure for an
operator familiar with the existing CLI, private configuration and service
supervisor. [Verification evidence](verification/issue62-settings.md) records
review and isolated rehearsals. Production deployment requires its own approval.

## Before starting

Use Python3.13+, PostgreSQL17 with pgvector and the approved0.6.15 package.
Keep the old0.6.14 checkout, Python environment, TOML configuration and protected
auth policy file. You need the existing database owner's upgrade privileges and
permission to pause writers. The running API account needs no new SQL grant.
Know how your installation starts the API, worker and optional model daemon.

Upgrade an existing schema027 store before starting the new API. Migration028
only adds `reranker` to the permitted administrative audit event types. It
preserves audit rows, table ownership and permissions. Documents, original
sources, embeddings, indexes, users, pins, jobs and checkpoints are retained.
The browser performs no SQL migration and never restarts services.

The presets use published INT8 ONNX files and a512-token query/passage limit.
The two multilingual artifacts match the measured model pins in the
[four-model report](benchmarks/2026-10-30-multilingual-rerankers/README.md).
Jina tiny here uses its official ONNX artifact; the earlier GGUF timings are a
different runtime configuration. All three presets are Apache2.0 models.
Model scores are ordering signals, not answer-confidence values.

## Upgrade an existing installation

Choose private paths in place of `/owned/`. The examples intentionally require
your actual configuration and an unused dump filename. A verified upgrade needs
enough space for the backup and a disposable restore database. Keep stopped
writers stopped until verification completes; include the API, worker and any
local CLI/MCP clients capable of writing to this store.

1. Inspect the source using the approved new package without starting its API:

   ```sh
   rag service --config /owned/server.toml preflight --source-version 0.6.14
   ```

2. Pause the installation's writers through its existing supervisor. Record
   which services and clients must be resumed. Do not assert `--writers-stopped`
   while any writer can still update this store.
3. Run the verified upgrade with a new private dump path:

   ```sh
   rag service --config /owned/server.toml upgrade --source-version 0.6.14 \
     --dump /owned/before-reranker-settings.dump --apply --writers-stopped
   ```

   Require `restore_verified`, `original_rows_unchanged` and an applied migration
   list containing `028_reranker_settings.sql`. Stop if restore or preservation
   verification fails. Preserve the dump and its generated proof files.
4. Start the approved API and resume the recorded writers. Sign in to
   `/dashboard/` with an existing administrator account.

The dashboard opens with the same accounts and knowledge. No embedding rebuild
is needed. Without an available matching local model, searches keep their
existing deterministic order. Upgrade itself installs no model service.

### Preserve an explicit existing model

Existing `[rerank] model` or `revision` fields preserve the old omitted identity
and `legacy-v1` budget defaults. Explicit URL, timeout and policy values remain
supported. A configuration without an explicit identity adopts mMARCO and the
focused6×600-character budget unless an explicit `policy` overrides it. The total
inference deadline remains1500ms.

A saved dashboard preset takes precedence over the server's `[rerank]` identity.
It is stored as `[reranker] profile = "..."` in the existing protected auth policy
file, not in the knowledge tables. Other provider and embedding settings stay
file-managed. To return to a custom file configuration, the operator can remove
that small policy section while dashboard writes are paused, retaining all
other tables and file permissions. Restart the server afterward and check the
**Current selection** on **Settings**. Preserve the old policy copy for recovery.

## Prepare and start the local runtime

The optional runtime is a separate process on literal loopback. Search never
downloads a model. Preparation downloads only the pinned public weights and
tokenizers; it sends no stored queries or passages to Hugging Face.

1. Install the optional CPU runtime dependencies in the approved environment:

   ```sh
   python -m pip install 'agentic-rag[reranker]==0.6.15'
   ```

2. Choose a model directory owned by the runtime operator:

   ```sh
   RAG_RERANK_MODELS="$HOME/.cache/agentic-rag/rerankers"
   mkdir -p "$RAG_RERANK_MODELS"
   ```

3. Download and verify the three presets explicitly:

   ```sh
   python -m agentic_rag.reranker_runtime prepare --models-dir "$RAG_RERANK_MODELS"
   ```

   Require a successful `prepared` result for `minilm-l6`, `mmarco` and
   `jina-tiny`. Model and tokenizer hashes come from the packaged
   [preset catalogue](../agentic_rag/reranker_profiles.json). A hash mismatch
   stops preparation; inspect and preserve the conflicting file before retrying.
4. Start the daemon in the foreground for the first check:

   ```sh
   python -m agentic_rag.reranker_runtime serve --models-dir "$RAG_RERANK_MODELS" \
     --host 127.0.0.1 --port 8766 --threads 4
   ```

   Keep the existing service on that port available for rollback; stop or move it
   only within the approved deployment window. A bind failure leaves it intact.
5. Read the loaded identities from another terminal:

   ```sh
   curl -fsS http://127.0.0.1:8766/v1/models
   ```

Expect all three model aliases and their artifact SHA256 values. Startup checks
both local files before advertising a model. For supervised operation use this
same command with your existing process supervisor; there is no new automatic
system service. If you change the port, set `[rerank] url` to the same literal
loopback origin in the server TOML and restart the server before selection.

## Select a model in the dashboard

Use an existing human administrator account. Regular knowledge members and
machine keys cannot change server settings. Prepare the desired model before
opening the page; unavailable options cannot be applied.

1. In `/dashboard/`, select **Settings** in the sidebar.
2. Select the desired option in **Reranker model**. Read its language support
   and availability. Choose Jina tiny only when English support is sufficient;
   there is no automatic language detection or per-language model routing.
3. Select **Preview model change**. The service verifies the pinned advertised
   identity and ranks a fixed synthetic positive/negative example. The preview
   names the target model and leaves the current selection unchanged.
4. Select **Apply model change**. Require the saved notice and the new value
   under **Current selection**. Reload to verify persistence.

The service repeats the model check and revalidates administrator authority
before committing. A stale page, failed check or revoked session retains the
previous setting. Saved selections apply to subsequent ambiguous auto searches
from REST and remote MCP; an in-flight search keeps one model snapshot.
Explicit lexical/hybrid search, `rerank=off`, exact identifiers and other existing
bypasses keep their deterministic path.

## Check operation and recover

Compare a representative authorized question with `--rerank off` and the normal
auto route. Confirm original sources and citations are intact. Availability on
**Settings** is a point-in-time identity check, not a capacity guarantee. mMARCO
can exceed the deadline under CPU contention. The daemon admits one native call
at a time and rejects additional pressure promptly. Timed-out native work holds
that slot until it finishes; the client keeps deterministic ordering.

If a preview reports **unavailable**, check `/v1/models`, the configured port and
the daemon's startup result first. Prepare missing files explicitly; do not
raise the search deadline to make the check pass. If the page is stale, reload
and preview again. No stored knowledge needs repair after a failed model check.

An interruption before the migration transaction commits leaves schema027 and
its marker unchanged. Retry with a new dump filename; the command verifies a
new backup before applying missing work. After a successful migration, repeating
the upgrade applies no migrations. A crash after the settings file replacement
leaves a prepared audit entry. The next policy apply reconciles its old/new file
hash and finishes the journal; unknown external drift refuses further changes
until the operator reconciles the protected policy and audit.

To roll back code, pause writers and restart the prior0.6.14 API/worker/client
environments with their saved configuration. Keep additive migration028 and its
audit history; old code accepts the additional marker and ignores `[reranker]`.
The old default model daemon/configuration must be available to recover its old
neural ordering; deterministic fallback works without it. Verify existing login,
local reads, REST and remote MCP before resuming writers. Do not restore an older
database over writes accepted after the backup. A full restore requires a
separately approved recovery plan that preserves those later writes.

## Terms

- Preset: one supported model identity, tokenizer and input budget.
- Artifact SHA256: the checksum of a pinned local model file.
- ONNX: the offline CPU model format used by this runtime.
- Policy file: the protected server file holding accounts, scopes and the preset.
- Administrative audit: durable records of settings and account changes.
- Deterministic fallback: the original eligible search order retained when model
  inference is bypassed, unavailable, invalid or timed out.

Recheck this playbook after changing a preset, runtime, migration, authority
boundary or upgrade source version.
