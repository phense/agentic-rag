# Antigravity integration

agentic-rag integrates with Google Antigravity (`agy` CLI, Antigravity App,
Antigravity IDE, and ACP hosts such as T3 Code) through one owned native plugin
package or the existing `rag install --agy` hook installer. Both use the same
PostgreSQL + pgvector store, audited write gateway, and checkpoint/mining
machinery shared with Claude Code and Codex.

## Native plugin package (recommended)

The native Antigravity plugin bundles the manifest, both MCP privilege levels,
and lifecycle hooks inside one ownership-tracked directory without modifying
foreign user `hooks.json` or `mcp_config.json` files:

```text
<config-dir>/plugins/agentic-rag/
├── .antigravity-plugin/plugin.json
├── mcp_config.json
├── hooks.json
└── .rag-package.json
```

### Install for standalone Antigravity CLI, App, and IDE

Preview first, then apply into `~/.gemini/config/plugins/agentic-rag`:

```sh
rag plugin install --host antigravity \
  --destination ~/.gemini/config/plugins/agentic-rag \
  --python /absolute/path/to/agentic-rag-python \
  --config /absolute/path/to/config.toml

rag plugin install --host antigravity \
  --destination ~/.gemini/config/plugins/agentic-rag \
  --python /absolute/path/to/agentic-rag-python \
  --config /absolute/path/to/config.toml \
  --apply
```

Validate with Antigravity and confirm ownership:

```sh
agy plugin validate --strict ~/.gemini/config/plugins/agentic-rag
agy plugin list --json
rag plugin doctor --host antigravity --destination ~/.gemini/config/plugins/agentic-rag
```

### Install for custom `--gemini-dir` or ACP hosts (such as T3 Code)

Hosts that launch `agy acp` with a separate `--gemini-dir` read their own
`<gemini-dir>/config/plugins/` directory instead of `~/.gemini/config/plugins/`.
Run the same preview-and-apply commands targeting that directory:

```sh
rag plugin install --host antigravity \
  --destination /absolute/antigravity-config/plugins/agentic-rag \
  --python /absolute/path/to/agentic-rag-python \
  --config /absolute/path/to/config.toml \
  --apply
```

Start a new Antigravity session (or T3 thread) so Antigravity discovers the new
MCP servers and hooks. The plugin coexists cleanly with other installed plugins
such as `engineering-method` and `writing-method`.

### Read-only package

Pass `--read-only` to generate a read-only plugin that exposes only
`agentic-rag-ro` (`--read-only`, `RAG_READONLY=1`, connecting as `rag_reader`)
and installs an empty `hooks.json` (no write tools, no cancellation tool, and
no capture hooks):

```sh
rag plugin install --host antigravity \
  --destination /absolute/path/to/agentic-rag-ro \
  --python /absolute/path/to/agentic-rag-python \
  --config /absolute/path/to/config.toml \
  --read-only --apply
```

## MCP privilege levels

The default native Antigravity plugin configures both stdio MCP servers in
`mcp_config.json`:

- **`agentic-rag`**: read-write main-session tools (`agentic_rag.plugins.mcp`).
  Uses `rag_writer` in standalone mode and adds `memory_request_status` /
  `memory_request_cancel` in central-service client mode.
- **`agentic-rag-ro`**: read-only tools (`agentic_rag.plugins.mcp --read-only`
  with `RAG_READONLY=1`). Connects as `rag_reader` in standalone mode and omits
  every mutation and cancellation tool.

## Lifecycle hooks and ACP transcripts

The plugin root `hooks.json` registers one named hook (`agentic-rag`) routed
through `agentic_rag.plugins.lifecycle --host antigravity --event <Event>`:

| Event | Timeout | Behavior |
|---|---|---|
| `SessionStart` | 10 s | Injects startup pins, domain map, project context, and continuation checkpoint as `{"injectSteps": [{"systemMessage": {"systemMessage": ...}}]}`; fails closed visibly on DB error. |
| `PreInvocation` | 5 s | First invocation of a turn (`invocationNum == 0`): detects trailing `/compact` (manual `PreCompact` + compact prompt injection), new automatic-compaction marker (`CHECKPOINT` / `<CONTEXT_SUMMARY>`), or selective error-signature recall. |
| `Stop` | 30 s | Attaches the `/compact` summary as bounded secret-stripped handoff (`PostCompact`) and enqueues the transcript delta for mining. |

Non-interactive, subagent, sidechain, fork, maintenance, and recursive stop
payloads are suppressed and return `{}`. `AGENTIC_RAG_HOOKS_DISABLE=1` disables
hook execution without deleting spooled data.

`agentic_rag/hooks/agy.py` uses `workspacePaths[0]` when present and falls back
to top-level `cwd`. `agentic_rag/transcript_agy.py` unwraps both standalone
`<USER_REQUEST>` blocks and nested ACP `<user_request>` blocks while stripping
`<t3_code_instructions>` and `<runtime_info>` wrappers so `/compact` detection,
prompt recall, and session mining read only the actual user text.

## Migrating from legacy `~/.gemini/config/hooks.json`

If you previously installed hooks with `rag install --agy`, disable the
`"agentic-rag"` entry in `~/.gemini/config/hooks.json` (set `"enabled": false`,
or restore its recorded rollback file) when activating the native plugin.
Running both the legacy global hook and the native plugin at the same time
causes Antigravity to execute the `agentic-rag` hooks twice.

`rag install --agy` remains supported for hooks-only setups and also accepts
`--agy-config-dir /absolute/antigravity/config` (mutually exclusive with
`--agy-home` and `--restore`). It emits a warning if a native plugin
`hooks.json` already exists under that config directory.

## Update, uninstall, and recovery

```sh
# Update in place (retains recorded --python, --config, and --read-only)
rag plugin update --host antigravity --destination <plugin-dir> --apply

# Remove only unmodified owned files (keeps .rag-package.json recovery record)
rag plugin uninstall --host antigravity --destination <plugin-dir> --apply

# Recover an interrupted update or uninstall
rag plugin recover --host antigravity --destination <plugin-dir> --apply
```

Uninstalling removes only files owned by `.rag-package.json`. It never deletes
database state, transcripts, or foreign plugin/config files.

## Upgrade compatibility and verification scope

This change adds no PostgreSQL migration (schema 039 unchanged), no database
role changes, and no central-service protocol changes. Running Claude Code,
Codex, OpenCode, and central-service deployments remain unaffected.

Plugin validation (`agy plugin validate --strict`), discovery
(`agy plugin list --json`), stdio MCP tool registration for both `agentic-rag`
and `agentic-rag-ro`, and hook execution are verified with `agy` 1.5.14 on
macOS. Long-session automatic server-side compaction remains tracked separately
under Issue #14.
