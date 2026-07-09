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
`[curation]`, `[worker]`. Unknown sections and unknown keys inside a known
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

Controls what the SessionStart hook injects into a new Claude Code
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

The `claude -p` call every mining and curation pass makes — using
whatever your Claude Code CLI is authenticated with (your Claude
subscription or an API key; your choice).

| Key | Field | Default | What it does |
|---|---|---|---|
| `model` | `llm_model` | `"haiku"` | Claude model alias passed to `claude -p --model`. |
| `timeout` | `llm_timeout` | `300` | Seconds before a `claude -p` call is killed as hung. |
| `bin` | `llm_bin` | `"claude"` | Name or path of the CLI binary invoked for mining/curation LLM calls. |

## `[mining]`

Session-mining behavior — see [05 · Session mining and
curation](05-session-mining-and-curation.md) for the full pipeline.

| Key | Field | Default | What it does |
|---|---|---|---|
| `debounce_seconds` | `mine_debounce_seconds` | `600` | Delay after a session's Stop event before its mine job becomes due — coalesces rapid-fire turns into one `claude -p` call instead of one per turn. |
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

## Next →

[07 · Privacy, cost & control](07-privacy-and-cost.md) — auth-agnostic
LLM calls (your Claude subscription or API key), the secret-stripping
gateway, the role matrix, and how
backups get restore-tested rather than trusted blindly.
