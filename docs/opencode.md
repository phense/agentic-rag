# OpenCode and DeepSeek integration

Unreleased source addition after 0.5.0. OpenCode 1.18.30 is the verified host;
DeepSeek Flash is the verified native model. The adapter is model-independent:
selecting Pro does not require another RAG installation.

## Install on the execution host

From a retained checkout with its existing Python 3.13+ environment:

```sh
uv run rag install --opencode --check
uv run rag install --opencode
```

Install on the Mac when T3 on Windows connects to that Mac environment. The
loader lives at ~/.config/opencode/plugins/agentic-rag.js. XDG_CONFIG_HOME and
OPENCODE_CONFIG_DIR are respected; an explicit --opencode-config-dir PATH wins.
Check mode writes nothing. Keep the checkout and virtualenv at the same paths;
the loader imports packaged JavaScript and invokes that virtualenv's Python.
The bridge explicitly imports Python from the same package root as its JS.

Finish active work, refresh T3's provider status and start a new thread. A cached
OpenCode helper may need to become idle or restart before loading the plugin.
Ask the model whether it received agentic-rag startup context; skill loading and
RAG hook loading are distinct checks. Existing Engineering Method can coexist.

The installer changes only its owned loader and creates missing parent
directories. Foreign/modified loader bytes and symlinked destination directories
are refused. A config hook adds agentic-rag-ro only if absent, using the reader
role. Existing MCP entries, including disabled ones, providers, permissions,
model choices and other plugins remain untouched. Automatic hooks use audited
checkpoint/queue APIs; they do not grant model or subagent memory-write tools.
The existing read-write MCP remains a separate, explicitly authorized surface.

## What runs

| Native hook | RAG action |
|---|---|
| chat.message | Capture the real prompt and invalidate cached context for that turn. |
| experimental.chat.system.transform | Restore startup/resume context and selective recall as transient system context. Reconcile a completed summary before the next model request. |
| experimental.session.compacting | Persist deterministic checkpoint, enqueue existing asynchronous enrichment, append handoff instructions. |
| session.compacted | Attach matching bounded summary and invalidate cached context. |
| session.idle / idle session.status | Export completed prose/tool names and enqueue debounced mining. |

Child sessions (parentID present) are excluded from automatic context/projection
and write paths; their read-only MCP access remains available. Session identity
is namespaced as opencode:<native-id> in RAG. Compaction is matched to the actual
compaction request's message ID and manual/auto flag, never merely to the most
recent checkpoint. Durable empty boundary records make subsequent enrichment
cursors resolvable even across compactions with no new prose.

OpenCode has no reliable SessionEnd hook. Idle is the tail-capture boundary;
a process killed before idle can miss its final tail until that session resumes.
The same callbacks cover auto compaction, while the native smoke exercised manual
compaction; real long-running automatic compaction remains an operational check.
Experimental hook names must be revalidated when upgrading OpenCode.

## Data, limits and failures

The SDK reads at most 200 recent messages from the active main session. Projection
merges them by stable identity into private mode-0600 JSONL files under
~/.agentic-rag/opencode/transcripts. It excludes reasoning, tool arguments/results,
synthetic or ignored context, compaction summaries and incomplete assistant
messages. Prose is secret-stripped before persistence. Each message contributes
at most 16,000 characters and 100 tool names; the file is capped at 8 MiB, omitting
oldest records with a logged warning. A single gap exceeding 200 host messages
can omit older uncaptured material. This is bounded capture, not a full transcript
archive. Canonical knowledge and checkpoints remain in the same PostgreSQL store.

Model-bound RAG context is secret-stripped again. Existing context budgets,
project scope, exact-pin priority and selective recall gates remain authoritative.
No provider call occurs inside a RAG hook. The existing worker still uses its
configured Codex/Claude mining/enrichment provider: selecting DeepSeek for coding
does not change that provider or replay historical sessions. Recalled knowledge
is sent as context to the coding model selected in OpenCode.

Each SDK request has a five-second deadline; each Python hook process has a
15-second deadline and 256 KiB output limit, with a 4 MiB input bound. A model
callback may perform several bounded operations. Errors do not abort the coding
session; context failures are visible, and asynchronous failures are shown in
subsequent context. Python diagnostics are secret-scrubbed in the existing hook
log. SDK/spawn failures use a generic visible warning. No cloud RAG service,
model routing, schema migration or extra scheduler is installed.

## Remove or disable

```sh
uv run rag install --opencode --uninstall --check
uv run rag install --opencode --uninstall
```

Only the exact generated loader is removed. Restart the helper afterward.
Modified loaders require inspection; they are never blindly overwritten. To move
the installation, uninstall from the old source/interpreter first. --restore is
for the other host installers; this target uses owned-file uninstall. The existing
AGENTIC_RAG_HOOKS_DISABLE environment switch stops its lifecycle actions.

## Verification

A later production check used T3 0.0.40 with OpenCode 1.18.30 on the Mac and
DeepSeek Flash. After provider refresh and a new T3 thread, the model recognized
injected canonical context and completed an actual agentic-rag-ro_memory_search
call with a one-time read approval. Native T3 tool events confirmed completion
and a result payload. The user authorized cloud processing for this check.
This verifies the T3 context/read path; compaction evidence below comes from the
separate native OpenCode test, not a T3 compaction run.

See [OpenCode evidence](verification/opencode.md). Run Python tests plus
node --test tests/test_opencode_plugin.mjs; Node is required for the JS adapter
checks. Native testing used the real local OpenCode server and DeepSeek API,
with synthetic data in agentic_rag_test. A test-only harness suppressed worker
spawning; queue persistence, checkpoint persistence and handoff restoration were
real. No synthetic data was written to the production knowledge store. A wheel
must contain integrations/opencode/plugin.mjs and support check mode after an
isolated installation.

Official references checked 2026-09-11:
- https://opencode.ai/docs/plugins/
- https://github.com/anomalyco/opencode/blob/v1.18.30/packages/plugin/src/index.ts
- https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/session/compaction.ts
- https://github.com/anomalyco/opencode/blob/v1.18.30/packages/sdk/js/src/gen/sdk.gen.ts
