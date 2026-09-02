# Quick start

*What you'll learn: the exact prerequisites, the install order (and why it's
order-sensitive), your first `rag save` and `rag search`, and how to confirm
everything is wired up.*

## Prerequisites

Install these first — agentic-rag doesn't bundle or manage any of them:

| Requirement | Why |
|---|---|
| **PostgreSQL 17** with the [`pgvector`](https://github.com/pgvector/pgvector) extension | The schema uses `halfvec`, which needs pgvector ≥ 0.7. This is where documents, chunks, and edges live. |
| **[Ollama](https://ollama.com)**, with the embedding model pulled | `ollama pull bge-m3` — `bge-m3` produces the 1024-dim embeddings the schema is built for. Search degrades to full-text-only if Ollama is unreachable, but embeddings need it. |
| **An authenticated LLM CLI** | Session mining and curation support `codex exec` (authenticate with `codex login`) and `claude -p`. Select it in `[llm]`; Claude/Haiku is the compatibility default. Embeddings stay local (Ollama/`bge-m3`). |
| **[`uv`](https://docs.astral.sh/uv/)** | Dependency management and running the project. |
| **Python ≥ 3.13** | `uv sync` will pick this up automatically if it's on your machine. |

Confirm the pieces you're less sure about before moving on:

```bash
psql --version          # want 17.x
ollama list              # bge-m3 should be in there after the pull below
codex login status       # for provider = "codex"
# or: claude --version   # for provider = "claude"
```

## Install, in this exact order

The four commands below have a hard dependency order. Run them from the
project directory:

```bash
uv sync
uv run rag init-db
uv run rag domain add science --description "Notes on scientific topics"
uv run rag install
```

Here's why the order matters:

1. **`uv sync`** — installs the project and its dependencies into a local
   virtual environment.
2. **`rag init-db`** — creates the Postgres database (if it doesn't exist
   yet), applies the schema in `sql/`, and seeds the built-in `general`
   domain. **Run this before anything else that touches the database.**
3. **`rag domain add <name>`** — adds any extra domain you want documents
   organized under (`general` already exists after `init-db`, so this step
   is optional — skip it if `general` is enough for now, and add more
   domains later with the same command).
4. **`rag install`** — registers the `agentic-rag` and `agentic-rag-ro` MCP
   servers with the `claude` CLI (user scope) and merges the SessionStart /
   UserPromptSubmit / Stop hooks into `~/.claude/settings.json`.

**`rag install` does NOT create the database.** It only wires up MCP servers,
hooks, and (on macOS) job scheduling. If you run it before `rag init-db`,
every command that touches the store will fail with a connection or
schema error. `init-db` first, always.

On **macOS**, `rag install` also auto-schedules the nightly **backup** job
via `launchd` — nothing further to do for backups. The **maintenance** job
is optional and enabled separately: run `rag maintenance --install-launchd`
once you want it scheduled too. On **Linux**, there's no `launchd`, so
neither job is auto-scheduled; set up the equivalent cron jobs or a systemd
user timer yourself using the copy-pasteable recipes in
[`docs/deploy/scheduling-linux.md`](deploy/scheduling-linux.md).

After `rag install`, start a new Claude Code session (or restart your
current one) so it picks up the newly registered MCP servers and hooks.

## Platform support

**macOS and Linux are the supported, tested platforms.** The test suite runs
on both, and everything above works as written.

**Windows:** as of 0.2.0 the core no longer makes POSIX-only assumptions that
used to block it (the worker lock, CLI decoding, and CLI path resolution are
all cross-platform now), but **native Windows is not yet verified end-to-end** —
there is no Windows CI. If you want to run on Windows today:

- **WSL2 is the smooth path.** Inside WSL2 you're on Linux, so follow the Linux
  instructions — including the scheduling recipes in
  [`docs/deploy/scheduling-linux.md`](deploy/scheduling-linux.md).
- **Native Windows** additionally needs, beyond the prerequisites above (of
  which building `pgvector` is the main friction):
  - `[db] host = "localhost"` in your config — Windows has no local unix
    socket, so the default empty host won't connect (see
    [06 · Configuration reference](06-configuration-reference.md)).
  - If your `claude` CLI is a `claude.cmd` shim that can't be launched directly
    as a subprocess, point `[llm] bin` at a directly-runnable executable.
  - **No auto-scheduling** — `rag install` schedules the backup job on macOS
    only. On Windows, schedule the backup and maintenance jobs yourself with
    Task Scheduler.

## Your first save and search

Everything from here on can go through `uv run rag ...`, or plain `rag ...`
if `uv run` isn't your habit and the virtual environment is on your `PATH`.

Save a document. `--title`, `--domain`, and `--dtype` are required; the body
comes from `--body` or `--file`. Valid `--dtype` values are `concept`,
`lesson`, `signal`, `source`, `synthesis`, `memory`, `reference`, and
`index` — pick the one that best describes what you're writing:

```bash
uv run rag save --title "Photosynthesis: light vs. dark reactions" \
    --domain science --dtype concept \
    --body "Light reactions happen in the thylakoid membrane and produce \
ATP + NADPH; the Calvin cycle (dark reactions) uses those to fix CO2 into \
sugar in the stroma. The two stages are linked but spatially separate."
```

You should see something like:

```
created photosynthesis-light-vs-dark-reactions (1 chunks, 0 edges)
```

Now search for it. Hybrid search blends vector similarity with full-text
ranking into one ranked list:

```bash
uv run rag search "how do plants make sugar from light" --domain science
```

```
0.0328  photosynthesis-light-vs-dark-reactions [science/concept]
```

(Scores come from rank fusion across the vector and full-text signals, so
they're small numbers — what matters is the ordering, not the magnitude.)
Note the query didn't share many words with the document — that's the
vector half of the search doing its job. Drop `--domain` to search across
every domain, and add `--json` to either command for machine-readable
output.

## Verify it's working

`rag status` gives you one snapshot: document counts, background queue
health, and backup/curation freshness.

```bash
uv run rag status
```

```
documents:
  science              active     1
queue:
last local backup: —
```

Only domains that actually hold a document show up under `documents:` —
`general` won't appear yet since you haven't saved anything into it. An
empty `queue:` section is expected right after install — the mining queue
only fills up once you've had a Claude Code session with the hooks active.
No `last local backup` yet is also expected; that appears after your first
`rag backup` (or the first scheduled run).

If `rag status` runs without errors and shows the document you just saved,
the install is complete: Postgres, pgvector, Ollama, and the `rag` CLI are
all talking to each other correctly.

## Next →

[04 · Working with your memory](04-working-with-memory.md) — save, get,
search, and pin from the command line and from inside a Claude Code
session, plus a closer look at domains and `rag status`.
