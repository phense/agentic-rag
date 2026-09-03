# Configuration reference

*What you'll learn: every setting in `config.toml`, its default, what it
controls, where the file lives, and how the surrounding environment
(env vars, libpq) interacts with it.*

## The file

agentic-rag reads one TOML file:

```
~/.agentic-rag/config.toml
```

Every key is optional. There's no scaffolding step that generates this
file — if it doesn't exist, every field just takes its default and
agentic-rag runs anyway. You create it only to override something.

Sections mirror the dataclass groupings below: `[db]`, `[embed]`,
`[ollama]`, `[backup]`, `[pg]`, `[hooks]`, `[llm]`, `[mining]`,
`[curation]`, `[worker]`, `[continuity]`. Unknown sections and unknown keys inside a known
section are silently ignored — a typo doesn't fail loudly, it just doesn't
apply. Add only the sections and keys you want to change:

```toml
[db]
host = "10.0.0.5"

[backup]
cloud_dir = "/Volumes/Backup/agentic-rag"
```

### Overriding the file location

Set `AGENTIC_RAG_CONFIG` to point at a different path:

```bash
export AGENTIC_RAG_CONFIG=~/work/agentic-rag-staging.toml
```

This is the only `AGENTIC_RAG_*` environment variable that affects
configuration loading. There is no per-field environment override (no
`AGENTIC_RAG_DB_NAME`-style variables) — everything else goes through the
TOML file. (`AGENTIC_RAG_HOOKS_DISABLE` exists too, but it's a hook
kill-switch, not a config field — see [05 · Session mining and
curation](05-session-mining-and-curation.md).)

### Path fields and `~` expansion

Three fields hold filesystem paths: `backup_cloud_dir`, `backup_local_dir`,
`pg_bin_dir`. Any value you give them in TOML is expanded (`~` resolves to
your home directory) when the file loads. `backup_cloud_dir` and
`pg_bin_dir` default to unset (`None`) — no cloud copy, no bin-dir
override — until you configure them.

### libpq is still in charge of the connection

agentic-rag builds a minimal connection string from `[db] name`/`host` and
the role it's connecting as, then hands the rest to libpq. Standard
Postgres environment variables — `PGHOST`, `PGPORT`, `PGPASSWORD`,
`PGUSER`, `~/.pgpass` — are inherited normally, because agentic-rag never
sets or overrides them. If you're pointing at a networked Postgres and
need role passwords or a non-default port, use those, not a
config.toml field. See [10 · Architecture](10-architecture.md) for the
role matrix these connections authenticate against.

## `[db]`

Where the database lives.

| Key | Field | Default | What it does |
|---|---|---|---|
| `name` | `db_name` | `"agentic_rag"` | Postgres database name. |
| `host` | `db_host` | `""` | `""` connects over the local unix socket; set a hostname to reach a remote/networked Postgres (combines with libpq env vars for auth). |

## `[embed]`

The embedding model, fixed to what the schema expects.

| Key | Field | Default | What it does |
|---|---|---|---|
| `model` | `embed_model` | `"bge-m3"` | Ollama model tag used to embed every chunk. |
| `dim` | `embed_dim` | `1024` | Embedding dimensionality. Must stay `1024` — the schema hard-codes `halfvec(1024)`, and `rag init-db` refuses to run if this doesn't match. |

## `[ollama]`

| Key | Field | Default | What it does |
|---|---|---|---|
| `url` | `ollama_url` | `"http://localhost:11434"` | Base URL of the local Ollama server used for embedding calls. |

## `[backup]`

Local dumps always happen; a cloud/synced copy is opt-in.

| Key | Field | Default | What it does |
|---|---|---|---|
| `local_dir` | `backup_local_dir` | `~/.agentic-rag/backups` | Where `pg_dump -Fc` writes local backups. |
| `cloud_dir` | `backup_cloud_dir` | unset (`None`) | Opt-in second copy directory (e.g. a mounted/synced volume). Unset means local-only — nothing leaves the machine. |
| `keep_local` | `backup_keep_local` | `7` | How many of the newest local dumps `rag backup` keeps before deleting older ones. |
| `keep_daily` | `backup_keep_daily` | `14` | How many of the newest **cloud** dumps to keep (daily rotation slots; only applies once `cloud_dir` is set). |
| `keep_weekly` | `backup_keep_weekly` | `8` | Additional weekly **cloud** retention slots beyond the daily window — one extra dump per week, further back in time. |

## `[pg]`

| Key | Field | Default | What it does |
|---|---|---|---|
| `bin_dir` | `pg_bin_dir` | unset (`None`) | Directory containing `pg_dump`/`pg_restore`/`psql` when they aren't already resolvable on `PATH` (e.g. Postgres.app or a Homebrew keg-only install). agentic-rag also tries a handful of platform-specific fallback locations before giving up. |

## `[hooks]`

Controls what the SessionStart hook injects into a new supported
session, and doubles as the staleness threshold `rag review` uses for
pins. These fields have no section prefix in the underlying dataclass —
the loader matches them by bare field name, and `[hooks]` is their
canonical home.

| Key | Field | Default | What it does |
|---|---|---|---|
| `stale_days` | `stale_days` | `30` | Days after which a pin is flagged stale — both in the SessionStart injection and in `rag review`'s report. |
| `pin_budget_chars` | `pin_budget_chars` | `16000` | Character budget for pinned rules injected at session start; pins beyond the budget still get a visible warning rather than being silently dropped. |
| `context_docs` | `context_docs` | `5` | Max number of recently-relevant documents for the current project injected at session start. |

## `[llm]`

The CLI provider used by mining and curation. Public defaults remain
Claude/Haiku for backward compatibility; a Codex deployment can use ChatGPT
authentication without adding an API key.

| Key | Field | Default | What it does |
|---|---|---|---|
| `provider` | `llm_provider` | `"claude"` | `claude` or `codex`. |
| `model` | `llm_model` | `"haiku"` | Provider model or alias. |
| `reasoning_effort` | `llm_reasoning_effort` | `"high"` | Codex reasoning effort. |
| `timeout` | `llm_timeout` | `300` | Seconds before a provider call is killed as hung. |
| `bin` | `llm_bin` | `"claude"` | Name or absolute path of the configured CLI. Use an absolute path for unattended jobs. |
| `provider_backoff_seconds` | `provider_backoff_seconds` | `3600` | Delay before a provider-unavailable job becomes due again. |

Peter's deployed Codex configuration is:

```toml
[llm]
provider = "codex"
bin = "/Users/peter/.local/bin/codex"
model = "gpt-5.6-luna"
reasoning_effort = "high"
provider_backoff_seconds = 3600
```

Codex runs ephemerally in an empty temporary directory, ignores user/project
rules and plugins, uses read-only sandboxing, and returns schema-constrained
JSON. If authentication expires, run `codex login`. The claimed job returns to
`pending` without consuming an attempt, a one-hour backoff is applied, and the
worker stops that drain after the first provider-wide failure. `rag status`
shows the outage. Set `provider = "claude"`, its binary, and a Claude model for
the configuration-only rollback path.

## `[mining]`

Session-mining behavior — see [05 · Session mining and
curation](05-session-mining-and-curation.md) for the full pipeline.

| Key | Field | Default | What it does |
|---|---|---|---|
| `debounce_seconds` | `mine_debounce_seconds` | `600` | Delay after a session's Stop event before its mine job becomes due — coalesces rapid-fire turns into one provider call instead of one per turn. |
| `max_digest_chars` | `mine_max_digest_chars` | `12000` | Max size of the transcript digest built for the miner LLM. |
| `per_block_chars` | `mine_per_block_chars` | `800` | Max characters per transcript block inside that digest. |
| `dedup_threshold` | `dedup_threshold` | `0.90` | Cosine-similarity threshold (embedding space) above which a newly mined item is treated as a near-duplicate of an existing document and linked with a `duplicate_of` edge instead of saved fresh. This field has no `mine_` prefix in the dataclass — it maps into `[mining]` via the same bare-key fallback as the `[hooks]` fields. |

## `[curation]`

| Key | Field | Default | What it does |
|---|---|---|---|
| `budget` | `curation_budget` | `20` | Max number of items (duplicate merges plus refute-candidate reviews) one curation pass processes before stopping. |

## `[worker]`

Retry policy for the single-writer background worker that drains
`mining_queue`.

| Key | Field | Default | What it does |
|---|---|---|---|
| `max_attempts` | `worker_max_attempts` | `3` | Attempts a queued job gets before it's marked `error` and left for a human to inspect (`rag status`). |
| `backoff_seconds` | `worker_backoff_seconds` | `300` | Base retry delay; the actual wait is `backoff_seconds × 2^(attempts-1)` — exponential backoff. |

## `[continuity]`

Bounds deterministic capture and the context restored by SessionStart. These
values belong to agentic-rag's `~/.agentic-rag/config.toml`; they are not Codex
model-context settings.

| Key | Field | Default | What it does |
|---|---|---|---|
| `status_max_chars` | `checkpoint_status_max_chars` | `4000` | Maximum captured characters from `git status --short`; truncation becomes a checkpoint warning. |
| `render_max_chars` | `checkpoint_render_max_chars` | `8000` | Maximum restored checkpoint text. Runtime clamps lower values to the renderer's safe 192-character minimum. |
| `artifact_max` | `checkpoint_artifact_max` | `16` | Maximum approved root/spec/plan artifact paths captured; file bodies are never stored in the checkpoint. |

## Managed Codex configuration

`rag install --codex` separately manages selected values in
`~/.codex/config.toml`; it does not copy them into agentic-rag's TOML. The
installer preserves comments and every foreign key while enforcing this
continuity policy:

```toml
model_context_window = 600000
model_auto_compact_token_limit = 500000
model_auto_compact_token_limit_scope = "total"
experimental_compact_prompt_file = "/absolute/home/.codex/compact_prompt.md"

[features]
hooks = true
memories = true

[memories]
generate_memories = true
use_memories = true
disable_on_external_context = false
min_rollout_idle_hours = 6
max_rollout_age_days = 90
max_rollouts_per_startup = 32
max_raw_memories_for_consolidation = 1024
max_unused_days = 180
min_rate_limit_remaining_percent = 15
extract_model = "gpt-5.6-luna"
consolidation_model = "gpt-5.6-luna"
```

The 500000 total-token compaction limit leaves a 100K reserve inside the
configured 600000 window. This is a local operating policy, not the model's
maximum: official GPT-5.6 Sol and Luna documentation lists a 1,050,000-token
context window and says prompts above 272K input tokens receive higher
provider pricing for the full request. Long-context latency/quota impact must
therefore be measured during rollout rather than assumed neutral. See the
[official GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
and [GPT-5.6 Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

`disable_on_external_context = false` is intentional: native Codex memories
remain eligible even when agentic-rag injects external context. Inspect them
with `/memories`. They complement rather than replace the canonical
agentic-rag store.

The associated `~/.codex/hooks.json` entries set
`additionalContextLimit = 10000` for `SessionStart` and `5000` for
`UserPromptSubmit`; the other four handlers do not declare additional-context
budgets because they do not inject it. Run `/hooks` after installation and
trust only the commands you have inspected.

## Next →

[07 · Privacy, cost & control](07-privacy-and-cost.md) — auth-agnostic
LLM calls (your Claude subscription or API key), the secret-stripping
gateway, the role matrix, and how
backups get restore-tested rather than trusted blindly.
