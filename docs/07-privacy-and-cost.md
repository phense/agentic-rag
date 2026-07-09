# Privacy, cost & control

*What you'll learn: how agentic-rag's cost works on whatever Anthropic auth
you choose, what happens to secrets that wander into a saved document, who can
do what to your database, and how backups get proven to actually restore.*

## Cost: whatever Anthropic auth you choose

agentic-rag has no billing path of its own — it's auth-agnostic. Every AI call
in the system — session mining, curation's LLM-assisted steps — runs through
one chokepoint, `agentic_rag/llm.py`, and that chokepoint shells out to the
`claude` CLI you already have logged in (`claude -p ... --json-schema ...`).
There is no separate API client of agentic-rag's own; the `claude` CLI uses
whatever *it* is authenticated with, and that choice is yours.

That auth can be either of two things, and agentic-rag imposes neither and
refuses neither:

- **Your Claude subscription (OAuth login).** This is the same login your
  interactive Claude Code sessions use. Mining and curation add nothing beyond
  your existing plan — there's no per-token invoice, nothing extra to meter.
- **An `ANTHROPIC_API_KEY`.** If your `claude` CLI is set up against an API
  key, those `claude -p` calls are metered by Anthropic like any other API
  use. agentic-rag runs fine either way; the metering is between you and
  Anthropic, on the account you chose.

Either way, **embeddings are always local** — retrieval and re-embedding run
on your own Ollama (`bge-m3`) and cost nothing regardless of which auth the
`claude` CLI uses. Only the LLM-assisted steps (mining, curation) touch
Anthropic at all, and only through the CLI you already have.

Two environment details worth knowing:
- `_child_env` also strips `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
  `CLAUDE_CODE_ENTRYPOINT`, and `CLAUDE_CODE_EXECPATH` from the child process,
  so a `claude -p` call spawned from inside a session can't be mistaken for a
  nested session by the CLI it's calling.
- It also sets `AGENTIC_RAG_HOOKS_DISABLE=1` on the child, so that child's own
  Stop hook doesn't enqueue its own transcript for mining — otherwise a
  mining run could end up mining itself.

Ollama (embeddings) and PostgreSQL both run on your machine too. Nothing in
the default path calls a hosted service.

## The secret-stripping gateway

Every write goes through one gateway function, `save_document` in
`agentic_rag/store.py`. Before anything reaches disk, it runs `title`,
`body`, `meta`, and `provenance` through the redaction patterns in
`agentic_rag/secrets.py`:

```python
title, r1 = strip_secrets(title)
body, r2 = strip_secrets(body)
meta, r3 = strip_secrets_json(meta or {})
provenance, r4 = strip_secrets_json(provenance or {})
```

Edge evidence gets the same treatment when an edge is attached to a save —
evidence strings often come straight from a mined transcript quote, so
they pass through `strip_secrets` too before the edge is written.

`strip_secrets` matches on shape: OpenAI/Anthropic-style `sk-...` keys,
GitHub tokens (`ghp_`/`gho_`/`ghu_`/`ghs_`/`github_pat_`), AWS access key IDs
(`AKIA...`), Slack tokens (`xox...`), credentials embedded in a URL
(`scheme://user:pass@host`), bearer tokens, PEM private key blocks, JWTs, and
`key = value` / `key: value` assignments where the key name looks like
`password`, `secret`, `token`, `api_key`, or similar. Every match is replaced
with the literal string `[REDACTED]`.

`strip_secrets_json` walks `meta`/`provenance` recursively. It's stricter
about dict keys than the text pattern is: if a key itself looks secret-shaped
(`password`, `token`, `api_key`, `authorization`, `credential`, ...), the
*entire* value is replaced whole — because an arbitrary password string has
no reliable pattern to match on the value side, but the key name is a
reliable signal. Every other string value runs through the same
`strip_secrets` patterns as title/body.

This is defense on the way *in*: it's the code that runs on session-mined
content and anything saved via `rag save` or the MCP tools, before a byte
lands in Postgres. Each `SaveResult` reports a `redactions` count, so a
caller can see whether anything was caught.

If you've read the redaction regexes and think of a shape they miss, that's
useful — file it as an issue rather than assuming the list is exhaustive.
Pattern-matching secrets out of free text is inherently probabilistic, not a
guarantee.

## Local-first: your Postgres, not ours

There's no agentic-rag cloud service. `save_document`, `search`, and every
CLI command talk directly to a PostgreSQL database you run — `localhost` by
default, or another host you point `config.toml` at. Embeddings come from a
local Ollama model (`bge-m3`). Nothing in the default configuration phones
data anywhere: no telemetry endpoint, no hosted vector index, no third-party
sync.

The one place data leaves your machine at all is the `claude -p` call itself
(the same call your interactive Claude Code sessions already make), and the
optional cloud copy of your own backups if you configure `[backup]
cloud_dir` in `config.toml` — that's a path you choose (e.g. a mounted
network drive or cloud-synced folder), not a service agentic-rag runs.

## The role matrix: destruction protection by design

agentic-rag talks to Postgres through three login roles, defined in
`sql/002_roles.sql`, each with strictly less power than the one above it:

| Role | Can do | Cannot do |
|---|---|---|
| `rag_reader` | `SELECT` on every table | Any write |
| `rag_writer` | `SELECT`/`INSERT`/`UPDATE` on `domains`, `documents`, `edges`, `pins`, `mining_queue`; `SELECT`/`INSERT` (append-only) on `audit_log`; `SELECT` on `chunks` and `schema_migrations` | `DELETE`, `TRUNCATE`, `DROP` — anywhere, on anything |
| `rag_admin` | Everything | — used only by `migrate`, `purge`, `restore` |

The interesting row is `rag_writer`. It has no `DELETE` grant on `chunks` at
all — so how does re-chunking a document work when a document is edited?
Through one narrow door: `replace_chunks()`, a `SECURITY DEFINER` SQL
function that runs as the table owner, not as the calling role:

```sql
CREATE OR REPLACE FUNCTION replace_chunks(
    p_document_id uuid, p_contents text[], p_embeddings text[]
) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
...
    DELETE FROM chunks WHERE document_id = p_document_id;
    INSERT INTO chunks(document_id, idx, content, embedding) ...
$$;
GRANT EXECUTE ON FUNCTION replace_chunks(uuid, text[], text[])
    TO rag_writer, rag_admin;
```

`rag_writer` can call this function, but only ever with one `document_id`
scoping the delete — the function body deletes chunks for that document and
that document alone. There is no path from `rag_writer`'s grants to a
table-wide delete, truncate, or drop of anything. A bug in application code
that tries to run `DELETE FROM documents` or `TRUNCATE chunks` under the
`rag_writer` role fails at the database level, not just the application
level — the protection is enforced by Postgres's own grant system, not by
code discipline.

`rag_admin` has full privileges and is used only by `migrate`, `purge`, and
`restore` — operations that are explicitly destructive by intent (removing
refuted documents, restoring from a dump) and gated behind confirmation
flags in the CLI (e.g. `rag purge --yes`, `rag restore <dump> --yes`).

Every write through the gateway also appends a row to `audit_log`
(`actor`, `op`, `document_id`, `summary`) — `rag_writer` can insert there but
never delete or edit past entries, so the audit trail can't be quietly
cleaned up by the same role that's writing content.

## Backups that are actually tested

`rag backup` runs `pg_dump -Fc` into a local directory
(`agentic_rag/backup.py`), rotates old dumps by a keep-count you configure,
and — only if you've configured a `[backup] cloud_dir` that's actually
mounted — copies the dump there too and rotates that copy separately. If the
cloud directory isn't mounted, the backup still succeeds locally and a
warning is recorded rather than silently skipping the offsite copy.

A dump file sitting on disk is not the same claim as "this backup works." So
`rag maintenance` (`agentic_rag/maintenance.py`) runs a weekly,
**report-only restore-test**: on Sundays (or on demand with
`--verify-backup`), it takes the newest local dump, restores it with
`pg_restore` into an isolated, disposable scratch database — never the live
one — and compares document/chunk row counts against the live database:

```python
scratch = cfg.db_name + _SCRATCH_SUFFIX
if scratch == cfg.db_name:      # defensive — never the live db
    raise RuntimeError("scratch db name collides with the live db")
...
ok = restored["documents"] > 0 and \
    restored["documents"] >= live["documents"] * 0.5
```

The scratch database is dropped afterward whether the check passes or
fails. This step never touches the live store and never auto-remediates a
bad backup — it only tells you, in the maintenance audit log, whether last
night's dump actually restores to something sane. `rag restore` (the
real, deliberate recovery path) requires an explicit `--yes` and restores
inside a single transaction, so a failure partway through can't leave the
database half-dropped.

## Next →

[08 · Knowledge domains and import](08-knowledge-domains-and-import.md) —
domains as data, adding and classifying them, and importing an existing
llm-wiki store with `migrate`.
