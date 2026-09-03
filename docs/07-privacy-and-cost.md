# Privacy, cost & control

*What you'll learn: how agentic-rag delegates LLM billing to your configured
CLI provider, what happens to secrets that wander into a saved document, who can
do what to your database, and how backups get proven to actually restore.*

## Cost: whatever provider account you choose

agentic-rag has no billing path or direct provider API client of its own.
Every AI call runs through `agentic_rag/llm.py`, which invokes the configured
Codex or Claude CLI and therefore uses that CLI's account and limits.

Supported choices are:

- **Codex with ChatGPT authentication.** Run `codex login`; a deployment can
  select a Codex model and reasoning effort without storing an API key here.
- **Your Claude subscription (OAuth login).** This is the same login your
  interactive Claude Code sessions use. Mining, curation, and checkpoint
  enrichment use that authenticated CLI account rather than an agentic-rag
  billing path; provider plan limits still apply.
- **An `ANTHROPIC_API_KEY`.** If your `claude` CLI is set up against an API
  key, those `claude -p` calls are metered by Anthropic like any other API
  use. agentic-rag runs fine either way; the metering is between you and
  Anthropic, on the account you chose.

In every case, **embeddings are local** — retrieval and re-embedding run on
your own Ollama (`bge-m3`). The provider inputs are:

- **mining:** a secret-stripped transcript digest, live domain names, and
  secret-stripped copies of all matching pin bodies for global or matching
  path scopes without mutating stored pin text;
- **curation:** selected stored document bodies and contradiction evidence that
  previously passed through the document write gateway's secret stripping;
- **checkpoint enrichment:** a bounded, secret-stripped transcript delta.

Matching pin bodies receive defense-in-depth stripping on the copy assembled
for the mining prompt. The stored pin remains unchanged, so local rendering
and later edits retain the user-owned text.

Codex continuity enrichment uses the same provider seam. The deterministic
checkpoint capture secret-strips bounded Git output; the enrichment path
strips its transcript delta again and validates schema, grounding, and
secret-shaped output before persistence. The safety-critical checkpoint does
not depend on enrichment: `PreCompact` commits deterministic state locally
first, and a provider outage leaves enrichment pending without consuming its
attempt budget. `rag status` and SessionStart expose the outage; after `codex
login`, the next successful worker run closes the circuit automatically and
enriches the same checkpoint.

### Native Codex memories and external context

The managed Codex policy enables native Codex memories and sets
`disable_on_external_context = false`. That means native memory generation/use
remains eligible even when a hook supplies external agentic-rag context. This
is deliberate complementarity, not ownership ambiguity:

- inspect and manage native Codex memories with `/memories`;
- treat agentic-rag as the canonical, locally queryable and audited store for
  durable knowledge and explicit continuation checkpoints;
- apply your Codex account's data controls to native memory and model calls in
  addition to the local secret/capture limits described here.

If you do not want native memory operating alongside externally injected
context, change that Codex setting after considering that the next
`rag install --codex` intentionally restores the managed policy.

### Long-context pricing and latency

The installer configures `model_context_window = 600000` and a total-scope
`model_auto_compact_token_limit = 500000`, leaving a 100K reserve. This stays
within the official 1.05M GPT-5.6 context window, but it is above the official
272K input boundary where GPT-5.6 requests receive higher provider pricing for
the full request. Large inputs can also take longer. This repository does not
claim the 600K/500K policy is cost- or latency-neutral; Task 10 must measure it
in the real rollout. Current values and pricing conditions are documented on
the [official GPT-5.6 Sol page](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
and [GPT-5.6 Luna page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

Two environment details worth knowing:
- `_child_env` also strips `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
  `CLAUDE_CODE_ENTRYPOINT`, and `CLAUDE_CODE_EXECPATH` from the child process,
  so a `claude -p` call spawned from inside a session can't be mistaken for a
  nested session by the CLI it's calling.
- It also sets `AGENTIC_RAG_HOOKS_DISABLE=1` on the child, so that child's own
  Stop hook doesn't enqueue its own transcript for mining — otherwise a
  mining run could end up mining itself.

Ollama (embeddings) and PostgreSQL both run on your machine too. There is no
separate hosted RAG service, but the configured Codex or Claude CLI normally
contacts its provider for mining, curation, and checkpoint enrichment.

## Lifecycle capture and hook trust

The deterministic checkpoint intentionally captures references and bounded
state, not arbitrary bodies: canonical CWD/Git paths, branch/HEAD, a capped
`git status --short`, transcript cursor/fingerprint metadata, and approved
artifact paths. It does not store a transcript, diff, or artifact body.
Optional semantic enrichment receives a bounded redacted transcript delta and
rejects secret-bearing, transcript-like, diff-like, or unrecognized output
instead of persisting it.

Hooks are commands running under your account. `rag install --codex` can merge
and validate their JSON, but it cannot decide whether you trust them. After
installation, use `/hooks`, inspect all six `python -m
agentic_rag.hooks.…` commands/hashes, and trust only what you recognize. The
installer reports duplicated foreign `herdr-agent-state.sh` commands but
neither trusts nor removes them.

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
local Ollama model (`bge-m3`). There is no telemetry endpoint, hosted vector
index, or third-party sync.

The configured LLM provider receives the mining, curation, and checkpoint
enrichment inputs enumerated above. The transcript digest and checkpoint delta
are bounded; mining also includes all matching pin bodies, secret-stripped on
the provider-bound copy without mutating stored pin text. Separately,
`[backup] cloud_dir` can copy your backup to a path you choose (for example a
mounted network drive or cloud-synced folder); it is not a service agentic-rag
runs.

## The role matrix: destruction protection by design

agentic-rag talks to Postgres through three login roles, defined in
`sql/002_roles.sql`, each with strictly less power than the one above it:

| Role | Can do | Cannot do |
|---|---|---|
| `rag_reader` | `SELECT` on every table | Any write |
| `rag_writer` | `SELECT`/`INSERT`/`UPDATE` on `domains`, `documents`, `edges`, `pins`, `mining_queue`, and `continuation_checkpoints`; `SELECT`/`INSERT` (append-only) on `audit_log`; `SELECT` on `chunks` and `schema_migrations` | `DELETE`, `TRUNCATE`, `DROP` — anywhere, on anything |
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

Codex configuration rollback is separate from database backup/restore. A
changing `rag install --codex` creates a unique sibling backup for each
existing changed file and an atomically published mode-`0600` rollback record
under `~/.agentic-rag/state/`. The printed command is:

```bash
rag install --codex --restore /absolute/path/to/codex-rollback-<id>.json
```

Use that exact printed path. Restore authenticates the recorded backup and
installed-file identities and refuses concurrent substitutions rather than
overwriting them; retained recovery files are named in any manual-recovery
error. `rag install --codex --check` creates no backups because it writes
nothing.

## Next →

[08 · Knowledge domains and import](08-knowledge-domains-and-import.md) —
domains as data, adding and classifying them, and importing an existing
llm-wiki store with `migrate`.
