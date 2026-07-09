# 12 · Contributing

*What you'll learn: how to set up a dev environment with `uv`, how the test
database works and how to run the suite, the TDD expectation for changes,
a one-paragraph map of the code, and the doc-reminder git hook that keeps
this handbook honest.*

## Dev setup

agentic-rag is managed with [`uv`](https://docs.astral.sh/uv/). From a clone
of the repo:

```bash
uv sync
```

This creates a local virtual environment and installs the runtime
dependencies (`psycopg`, `httpx`, `mcp`, `pyyaml`) plus the dev group
(`pytest`). Python ≥ 3.13 is required — `uv` will pick up a matching
interpreter automatically if one is available.

You'll also need the same runtime prerequisites as a normal install — a
local **PostgreSQL 17** with **pgvector**, and **Ollama** with `bge-m3`
pulled — because the test suite exercises real Postgres connections and,
for some tests, real embedding calls rather than mocking the database away.
See [03 · Quick start](03-quick-start.md) for how to confirm those are in
place. One extra thing the test suite needs that a normal install doesn't:
the Postgres role you run as must be allowed to `CREATE DATABASE` — the
first test run creates the test database itself (see below).

## The test database

Tests run against a real Postgres database named `agentic_rag_test` —
never against the database you actually use day to day. This lives in
`tests/conftest.py`:

- A session-scoped `dbinit` fixture connects to the `postgres` maintenance
  database, creates `agentic_rag_test` if it doesn't already exist, then
  connects to it as the `owner` role and runs `DROP SCHEMA public CASCADE;
  CREATE SCHEMA public` followed by `db.apply_migrations()` — every file in
  `sql/`, in order, from scratch. So the schema in the test database is
  always exactly what's in `sql/` right now, not whatever migration history
  happened to accumulate.
- A function-scoped `conn` fixture then `TRUNCATE`s the content tables
  (`documents, domains, edges, pins, mining_queue, audit_log`) before each
  test and rolls back its own transaction afterward — tests don't leak
  rows into each other, and a test that never commits leaves nothing
  behind at all.
- An autouse `_isolate_home_paths` fixture patches every module-level
  `Path.home()`-derived constant (the worker's lock/log paths, the hooks'
  log path, the migration scratch dir) to a per-test `tmp_path`. No test may
  ever touch your real `~/.agentic-rag`.
- A `hook_env` fixture points hook/MCP code at the test database through
  `AGENTIC_RAG_CONFIG` (a throwaway `config.toml` in `tmp_path`) and points
  Ollama at a dead port on `localhost` — a deterministic "embeddings
  unavailable" path, rather than a flaky dependency on Ollama actually
  running during tests.

You don't create `agentic_rag_test` by hand — the first test run does it.
If your Postgres role can't create databases, create it once yourself
(`createdb agentic_rag_test`) and the fixture's existence check will just
skip past its own `CREATE DATABASE` call.

## Running the suite

```bash
uv run pytest
```

That's the whole invocation — `pyproject.toml` already points `pytest` at
`testpaths = ["tests"]`. Narrow it the normal pytest ways while iterating:

```bash
uv run pytest tests/test_store.py            # one module
uv run pytest tests/test_store.py -k slug    # one behavior
uv run pytest -x                             # stop at first failure
```

The suite covers every module below — config, db init, roles, the store
gateway, search, embeddings, chunking, secrets, domains, pins, migration
(including an end-to-end import test), mining, the worker, jobs, curation,
maintenance, backups, install, the CLI, the MCP server, and each hook —
each with its own `tests/test_*.py` file.

There's no CI wired up yet for this repo; running the suite locally before
you send a change is the check that stands in for it.

## The TDD expectation

This codebase was built test-first, module by module, and that's the
expectation for changes to it too: **write the failing test before the
code that makes it pass.** Concretely, for a new behavior or a bug fix:

1. Write (or extend) a test in the matching `tests/test_*.py` file that
   fails for the right reason — run it and read the failure, don't just
   assume it's red.
2. Write the smallest implementation change that makes it pass.
3. Run the full suite (`uv run pytest`), not just the one file — several
   modules here (the write gateway, the roles, the worker) have
   guarantees that other modules depend on, and a change that looks local
   can break an assumption two files away.

This isn't a stylistic preference. Guarantees like "every write goes
through `save_document()`" or "`rag_writer` can never issue a `DELETE`"
only hold if the tests that pin them down keep failing whenever someone
tries to route around them — which only works if the test existed before
the code did.

## Code layout

A one-line map of `agentic_rag/`, in roughly the order data flows through
it:

| Module | What it does |
|---|---|
| `config.py` | One TOML file (`~/.agentic-rag/config.toml`) parsed into a flat dataclass, with environment overrides for tests. |
| `db.py` | Role-scoped connections (`owner`/`reader`/`writer`/`admin`) and the SQL-file migration runner that applies `sql/*.sql` in order. |
| `store.py` | The write gateway — `save_document()` is the one path every write takes: secret stripping, slug uniqueness, chunk/embedding regeneration, dangling-edge resolution, audit row, one transaction. |
| `search.py` | The hybrid search wrapper — embeds the query (fail-open if Ollama is down) and calls the `hybrid_search()` SQL function. |
| `embed.py` | The Ollama embedding client — the only place embeddings are produced; models are never loaded in-process. |
| `chunker.py` | Structural Markdown chunking (headings, then paragraphs, then a hard split as a last resort) plus `slugify()`. |
| `secrets.py` | Deterministic secret-shaped-token stripping — the write gateway's first line of defense, run on every save. |
| `domains.py` | Domains as data — add/list, backing `rag domain`. |
| `pins.py` | User-owned standing rules injected at `SessionStart`; no cap, deterministic order, never written by automation. |
| `migration.py` | The `migrate` importer — brings an existing llm-wiki store in through the write gateway, idempotent by source id, never writing to the source. |
| `ultra_source.py` | Read-only readers for an llm-wiki source corpus (topic-partitioned Markdown + optional `memory.db`) that `migration.py` reads from. |
| `mining.py` | Session mining — one structured `claude -p` call per queue job, extracting candidate memories/lessons/signals, written through the gateway. |
| `worker.py` | The single writer — a short-lived, flock-singleton process that drains the mining queue, runs a bounded curation pass, and takes an opportunistic backup, then exits. |
| `jobs.py` | `mining_queue` plumbing shared by hooks and the worker; deliberately import-light so hooks never pull in `llm`/`mining`/`curation`. |
| `curation.py` | Bounded, justified curation that runs only inside the single writer — dangling-link resolution, exact-duplicate merges, contradiction review, refute/purge support. |
| `maintenance.py` | `rag maintenance` — spawns the worker if it's idle, rotates logs, and runs the weekly report-only restore-test. |
| `backup.py` | `pg_dump` backups — local always, an optional cloud copy when configured and mounted, rotation either way. |
| `install.py` | `rag install` — registers the MCP servers with the `claude` CLI, merges hooks into `~/.claude/settings.json`, and installs the platform scheduler. |
| `mcp_server.py` | The per-session MCP server — SQL plus one Ollama HTTP call for search, never a model in-process; read-write or read-only depending on `RAG_READONLY`. |
| `hooks/` | The three Claude Code hook entry points — `session_start.py`, `prompt_recall.py`, `stop_enqueue.py` — plus `common.py`'s shared rule: a hook never blocks a session, every error is swallowed and logged, and it always exits 0. |
| `cli.py` | The `rag` CLI — a thin `argparse` layer over everything above it. |

Deeper detail on how these fit together lives in
[10 · Architecture](10-architecture.md); the exact commands and MCP tools
each module backs are in
[11 · Reference — CLI & MCP](11-reference-cli-and-mcp.md).

## Keeping docs in lockstep with code

This handbook is expected to track the code, not lag behind it. Two things
help with that:

- **`BACKLOG.md`** at the repo root is the single, numbered backlog for
  open work — worked top-down, kept current, every open item carrying a
  reason it isn't done yet and a trigger for resuming it.
- **`CHANGELOG.md`** follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
  and [semantic versioning](https://semver.org/); it's pre-1.0, so entries
  summarize milestones rather than every commit.

### The doc-reminder git hook

`.githooks/pre-commit` is a **warn-only** habit-former, not a gate: if a
commit stages changes under `agentic_rag/` or `sql/` but nothing under
`docs/`, it prints the list of changed files and a reminder to consider
updating the handbook — then lets the commit proceed regardless. There's
deliberately no environment variable to silence it; the only way past it
is to either update the docs or accept the reminder and commit anyway.

It isn't wired up by default — Git only runs hooks from `.git/hooks/`
unless you point it elsewhere. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

That setting lives in your local `.git/config`, not in the repo, so every
clone (yours and every contributor's) opts in for itself.

## Next →

[99 · Design notes & rationale](99-design-notes.md) — why Postgres over
files, why a single writer, why domains are derived rather than declared,
and the data-safety choices behind all of it.
