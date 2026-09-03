# Architecture

*What you'll learn: the schema (documents, chunks, edges, domains, pins,
mining_queue, audit_log, continuation_checkpoints) and its constraints, the three-role
destruction-protection matrix and the `replace_chunks()` escape hatch, the
HNSW and GIN indexes that make search fast, the single write gateway, the
single-writer worker and its flock, the Claude and Codex lifecycle hooks, and the two
MCP servers. This chapter verifies against the actual SQL and Python — if
something here looks surprising, it's meant to; that's what makes it
architecture rather than a recap of [02 · The mental model](02-mental-model.md).*

Everything below lives in `sql/001_init.sql` through
`sql/007_checkpoint_predecessor.sql` and under `agentic_rag/`, including the
`continuity/` and `integrations/codex/` packages. `rag init-db`
applies the SQL files in filename order inside one transaction
(`apply_migrations()` in `agentic_rag/db.py`) and records each in
`schema_migrations(filename PRIMARY KEY, applied_at)` so re-running is a
no-op. `db.connect(cfg, role=...)` is the one place a role is chosen; every
connection returns `dict_row`-shaped rows.

## The schema

### `documents` — the unit of knowledge

```sql
CREATE TABLE documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    domain      text NOT NULL REFERENCES domains(name),
    dtype       text NOT NULL CHECK (dtype IN
                  ('concept','lesson','signal','source','synthesis',
                   'memory','reference','index')),
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    meta        jsonb NOT NULL DEFAULT '{}',
    provenance  jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','archived','refuted')),
    refuted_reason   text,
    refuted_evidence text,
    refuted_at       timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz,
    CONSTRAINT refuted_requires_justification CHECK (
        status <> 'refuted'
        OR (refuted_reason IS NOT NULL AND refuted_evidence IS NOT NULL
            AND refuted_at IS NOT NULL)
    )
);
```

`updated_at` is stamped by a `BEFORE UPDATE` trigger (`set_updated_at()`), not
by application code. The `refuted_requires_justification` CHECK is only half
of refutation's enforcement: a **deferred constraint trigger** added in
`005_plan2.sql` (`documents_refute_justified`, `DEFERRABLE INITIALLY
DEFERRED`) additionally requires, checked at COMMIT rather than per-statement,
that a refuted document has (a) a `supersedes` or `contradicts` edge touching
it, and (b) an `audit_log` row with `op = 'refute'`. Deferring to COMMIT means
a refuting transaction can write the status change, the edge, and the audit
row in any order — the trigger only cares that all three exist by the time
the transaction lands.

### `chunks` — what search actually touches

```sql
CREATE TABLE chunks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx         int  NOT NULL,
    content     text NOT NULL,
    embedding   halfvec(1024),
    tsv_en tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    tsv_de tsvector GENERATED ALWAYS AS (to_tsvector('german', content)) STORED,
    UNIQUE (document_id, idx)
);
```

`halfvec(1024)` is fixed to the `bge-m3` embedding model's output size —
`init_db()` refuses to run if `cfg.embed_dim != 1024`, so the schema and the
embedding model can't silently drift apart:

```python
if cfg.embed_dim != 1024:
    raise RuntimeError(
        f"embed_dim={cfg.embed_dim} but the schema fixes embeddings at "
        f"halfvec(1024) (bge-m3). To use another dimension, regenerate "
        f"sql/001_init.sql for that size first.")
```

`embedding` is nullable — a chunk can exist without a vector when Ollama was
unreachable at save time (see the gateway, below). `tsv_en`/`tsv_de` are
`GENERATED ALWAYS ... STORED` columns: Postgres computes and stores them on
every insert, unconditionally, for every chunk — there's no per-document
language switch. Chunk-splitting mechanics (structural, ~1000 chars target,
~4000 cap) are covered in [02 · The mental model](02-mental-model.md); this
chapter is about the row shape, not the splitter.

### `edges` — typed, dangling-safe graph

```sql
CREATE TABLE edges (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    src_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    dst_id     uuid REFERENCES documents(id) ON DELETE SET NULL,
    dst_slug   text NOT NULL,          -- survives even when dst_id is NULL
    predicate  text NOT NULL CHECK (predicate IN
                 ('references','extends','depends_on','complements',
                  'contrasts_with','informs','part_of','derived_from',
                  'supersedes','contradicts','duplicate_of')),
    evidence   text,
    confidence text CHECK (confidence IS NULL OR confidence IN ('high','medium','low')),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to   timestamptz,
    created_by text NOT NULL CHECK (created_by IN ('migration','mining','manual','claude')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (src_id, dst_slug, predicate)
);
```

`dst_id` can be `NULL` while `dst_slug` still names the intended target — a
*dangling* edge. `src_id` cascades on document delete; `dst_id` merely goes
`NULL` on delete (the slug still records what it pointed at). `created_by` is
a closed vocabulary too: only `migration`, `mining`, `manual`, or `claude` —
the CLI's `actor="cli"` gets mapped to `manual` before the row is written
(`_CREATED_BY = {"cli": "manual"}` in `store.py`). `valid_from`/`valid_to`
make edges bi-temporal, which is what `memory_timeline` reads.

### Operational tables

| Table | Key columns | Constraints / notes |
|---|---|---|
| `domains` | `name` (PK, text), `description`, `created_at` | Referenced by `documents.domain`; `general` is seeded by `domains.seed_defaults()` right after migrations apply. |
| `pins` | `document_id` (nullable FK → `documents`), `body`, `scope` (default `'global'`), `priority` (default `100`), `active` (bool), `last_verified` | `scope` is a free string interpreted by app code as `global`, a domain name, or an absolute project path — no CHECK constrains it. |
| `mining_queue` | `kind` CHECK(`mine`/`curate`/`backup`/`embed`/`checkpoint_enrich`), `session_id`, `transcript_path`, `payload` jsonb, `status` CHECK(`pending`/`processing`/`done`/`error`), `attempts`, `next_attempt_at`, `last_uuid`, `last_error`, `enqueued_at`, `finished_at` | `checkpoint_enrich` carries a checkpoint id plus the prior transcript cursor and is prioritized after maintenance but before ordinary mining/embed work. `idx_queue_due(status, next_attempt_at)` backs the due scan. |
| `continuation_checkpoints` | `(session_id, cursor)` unique, `turn_id`, fingerprint, source/trigger, cwd/project root, bounded Git/snapshot/enrichment/reference/warning JSON, predecessor cursor, lifecycle/quality, compaction/timestamps | Operational continuation state, separate from documents. Open rows are indexed by session and canonical project; new cursors supersede old open rows, history is retained, and writer has no delete grant. Snapshot/enrichment/compaction mutations append audit events. |
| `audit_log` | `id` (identity PK), `actor`, `op`, `document_id`, `summary`, `at` | Append-only by grant (see the role matrix) — nothing can edit or delete a past entry, including the role that writes it. |
| `schema_migrations` | `filename` (PK), `applied_at` | Bookkeeping only; `rag_writer` gets `SELECT`, nobody but the owner/admin connection writes to it. |

## Indexes

| Index | Table.column | Type | Purpose |
|---|---|---|---|
| `idx_chunks_embedding` | `chunks.embedding` | **HNSW**, `halfvec_cosine_ops`, `m=16, ef_construction=64` | Approximate nearest-neighbor vector search. |
| `idx_chunks_tsv_en` | `chunks.tsv_en` | GIN | English full-text search. |
| `idx_chunks_tsv_de` | `chunks.tsv_de` | GIN | German full-text search. |
| `idx_documents_domain` | `documents.domain` | btree | Domain-filtered listing/search. |
| `idx_documents_status` | `documents.status` | btree | Active/archived/refuted filtering. |
| `idx_edges_src` | `edges(src_id, predicate)` | btree | Outgoing-edge lookups (`memory_get`, graph traversal). |
| `idx_edges_dst` | `edges(dst_id, predicate)` | btree | Incoming-edge lookups. |
| `idx_edges_dangling` | `edges(dst_slug)` | btree, **partial** (`WHERE dst_id IS NULL`) | Fast "who's dangling on this slug" scan when a new document is saved. |
| `idx_queue_due` | `mining_queue(status, next_attempt_at)` | btree | The worker's "what's due right now" claim query. |
| `idx_audit_doc` | `audit_log.document_id` | btree | Per-document audit history (refute-justification trigger, `rag review`). |
| `idx_audit_op_at` | `audit_log(op, at DESC)` | btree | "When did curation last run" (`jobs.last_curation_at`). |
| `idx_continuation_checkpoints_session_open` | `continuation_checkpoints(session_id, state, updated_at DESC)` | btree | Latest same-session checkpoint for compact restoration. |
| `idx_continuation_checkpoints_project_open` | `continuation_checkpoints(project_root, state, updated_at DESC)` | partial btree | Startup/resume fallback within one canonical project. |

HNSW over the alternative (IVFFlat) is a fixed decision baked into
`001_init.sql`, not a runtime option; there's no config knob to switch index
types. `m`/`ef_construction` are also fixed at their `001_init.sql` values —
changing them means editing the migration and re-running it on a fresh index
build.

## The three-role destruction-protection matrix

Three Postgres **login roles**, created idempotently in `sql/002_roles.sql`
(`CREATE ROLE ... LOGIN` only if it doesn't already exist), each strictly
less powerful than the one above it. They're passwordless by default —
`db.dsn()` never sets a password field at all, relying on local peer/trust
auth — with an optional `ALTER ROLE ... PASSWORD` outside this SQL for
shared/remote Postgres instances.

| Role | Grants | Notably absent |
|---|---|---|
| `rag_reader` | `SELECT` on every table, including continuation checkpoints | Any write, anywhere. |
| `rag_writer` | `SELECT/INSERT/UPDATE` on `domains`, `documents`, `edges`, `pins`, `mining_queue`, and `continuation_checkpoints`; `SELECT` only on `chunks`; `SELECT/INSERT` on `audit_log` (append-only); `SELECT` on `schema_migrations`; `USAGE` on all sequences | `DELETE`/`TRUNCATE`/`DROP` on **anything** — not even checkpoints or audit rows it inserted. |
| `rag_admin` | `ALL` on all tables, `USAGE` on all sequences | Nothing — used only by `migrate`, `purge`, `restore`. |

`rag_writer` has *no* `DELETE` grant on `chunks`, which is the interesting
constraint: a document's chunks still need to be regenerated wholesale on
every re-save. The escape hatch is one `SECURITY DEFINER` function, scoped to
a single document per call:

```sql
CREATE OR REPLACE FUNCTION replace_chunks(
    p_document_id uuid, p_contents text[], p_embeddings text[]
) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n int;
BEGIN
    DELETE FROM chunks WHERE document_id = p_document_id;
    INSERT INTO chunks(document_id, idx, content, embedding)
    SELECT p_document_id, t.i - 1, t.c,
           CASE WHEN t.e IS NULL THEN NULL ELSE t.e::halfvec END
    FROM unnest(p_contents, p_embeddings) WITH ORDINALITY AS t(c, e, i);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
REVOKE ALL ON FUNCTION replace_chunks(uuid, text[], text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION replace_chunks(uuid, text[], text[])
    TO rag_writer, rag_admin;
```

`SECURITY DEFINER` means the function body runs with the privileges of the
function's *owner* (who does have `DELETE` on `chunks`), not the calling
role. `rag_writer` can only reach it through this one signature, which always
scopes the `DELETE` to exactly the `p_document_id` it was called with —
there is no argument combination that empties the table. `REVOKE ALL ...
FROM PUBLIC` closes the default-executable-by-everyone hole before the
explicit `GRANT` reopens it for exactly the two roles that need it.

The matrix survives `pg_restore --clean` on purpose. `005_plan2.sql` sets
`ALTER DEFAULT PRIVILEGES` for `rag_reader` (`SELECT` on future tables) and
`rag_admin` (`ALL` on future tables), but *deliberately not* for
`rag_writer`:

```sql
-- WRITER rights are deliberately PER-TABLE (the §8 matrix: documents S/I/U,
-- chunks SELECT-only, audit_log append-only), so there must be NO blanket
-- writer default: pg_restore --clean recreates every table, default
-- privileges fire at CREATE and are ADDITIVE on top of the dump's ACLs — a
-- writer default would silently re-grant UPDATE on audit_log and INSERT on
-- chunks at every restore (observed live during Task 4).
```

Every migration that adds a table has to grant `rag_writer` explicitly,
per-table — there's no default-privileges shortcut for that role. This is
the concrete mechanism behind the destruction-protection claim: it isn't
"the app is careful," it's "the database physically cannot do it even if the
app tries," and that property is re-verified, not just assumed, across a
restore.

## The write gateway: `save_document()`

Every content write — `rag save`, the MCP `memory_save` tool, the session
miner, the wiki importer — calls exactly one function,
`save_document()` in `agentic_rag/store.py`. It runs as one transaction and
does, in order:

1. **Strip secrets** from `title`, `body`, `meta`, `provenance` (via
   `agentic_rag/secrets.py` — see [07 · Privacy, cost & control](07-privacy-and-cost.md)
   for the redaction patterns) before anything else touches them.
2. **Validate the domain** exists (`SELECT 1 FROM domains WHERE name = %s`) —
   fails fast with a "create it first" error rather than a broken FK.
3. **Insert or update** `documents`. On update, `meta`/`provenance` are
   merged (`meta || %s::jsonb`), not replaced — a re-save can't silently
   drop keys a previous save added. A new document without an explicit slug
   gets one from `slugify(title)`, uniquified by appending `-2`, `-3`, ... if
   taken (`_unique_slug()`).
4. **Re-chunk and re-embed**, then swap chunks atomically via
   `replace_chunks()`. Embedding is fail-open: `try_embed_texts()` returns
   `None` when Ollama is unreachable, the save still lands with `embedding =
   NULL` for every chunk, a warning is added to the result, and an `embed`
   job is enqueued to `mining_queue` for later retry — the document is never
   held hostage to Ollama being up.
5. **Upsert edges** out of this document. The `ON CONFLICT` clause uses
   `COALESCE(EXCLUDED.evidence, edges.evidence)` — a re-save without evidence
   text can never clobber evidence a previous save recorded, which matters
   because `rag_writer` has no `DELETE` on `edges` either; this `UPDATE` path
   is the *only* way edge metadata changes.
6. **Resolve dangling edges elsewhere** that were waiting on this slug:
   `UPDATE edges SET dst_id = <this doc> WHERE dst_slug = <this slug> AND
   dst_id IS NULL AND src_id <> <this doc>` — no separate repair pass, no
   cron job; the moment the target exists, every edge that named it resolves.
7. **Write one `audit_log` row** — actor, `op='save_document'`, document id,
   a one-line summary (chunk count, edge count, redaction count).
8. **Commit.** Any exception rolls back explicitly — `save_document()` never
   leaves a connection (which, over MCP, is long-lived) sitting in an aborted
   transaction.

Two more gateway functions worth knowing: `set_domain()` is the *one*
write that deliberately skips re-chunking — domain lives on `documents`, not
on chunk content, so moving a document doesn't touch `chunks` at all.
`reembed_document()` is the queued-`embed`-job's retry path: it re-chunks,
calls the *non-fail-open* `embed_texts()` (raises on failure rather than
degrading), and lets the worker's own backoff own the retry — the function
itself must not swallow an Ollama outage.

## Search: `hybrid_search()` and Reciprocal Rank Fusion

`search()` in `agentic_rag/search.py` embeds the query (`try_embed_texts`,
fail-open — `None` on failure, with a `"embedding unavailable — full-text
search only"` warning) and calls one SQL function, `hybrid_search()` in
`sql/003_search.sql`, with the query text, the query vector (or `NULL`), an
optional domain filter, and `k`.

Inside, three independent candidate lists are built, each already ranked and
each capped at its own top 50, and each already excluding anything that
isn't `status = 'active'`:

- **`vec`** — chunks ordered by `embedding <=> query_vec` (cosine distance,
  ascending — closer first), skipped entirely when `query_vec IS NULL`.
- **`ts_en`** — chunks where `tsv_en @@ websearch_to_tsquery('english',
  query_text)`, ordered by `ts_rank_cd` descending.
- **`ts_de`** — the same against `tsv_de` with the German config.

The three lists are unioned and fused by **Reciprocal Rank Fusion**, `k=60`:
every chunk's score is `sum(1.0 / (60 + rank))` across whichever list(s) it
appears in, computed once per `chunk_id`. The final result is `ORDER BY
score DESC, slug` (the `slug` tie-break makes ranking fully deterministic,
not just "usually stable") `LIMIT k`, joined back to `chunks`/`documents` for
title, slug, domain, dtype, a **plain 400-character truncation** of the
chunk (`left(c.content, 400)` — no highlighting), `verified_at`, and
`provenance`.

A chunk that scores on two signals outranks one that only scores on one,
without any hand-tuned blend weight — that's the whole point of RRF over a
manually-weighted average. When the query embedding failed, the `vec` CTE
contributes nothing (its `WHERE query_vec IS NOT NULL` guard excludes every
row) and the ranking degrades to FTS-only automatically, with the warning
already attached by `search()` before the SQL call.

## The single writer: flock, never a PID file

Exactly one `worker.py` process may be draining `mining_queue` at any time,
across however many supported sessions are open. The guarantee is a kernel
`flock`, not an application-level check:

```python
fd = path.open("a+")
fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
```

on `~/.agentic-rag/state/worker.lock`. If the lock is held, `acquire_lock()`
returns `None` and `main()` returns `0` immediately — **contention means
skip, never queue up another attempt.** The reason it's `flock` and not a PID
file: the kernel releases the lock the instant the holding process dies, for
any reason, including a hard `SIGKILL`/jetsam kill — a PID file can outlive
its process and permanently wedge the singleton; a `flock` cannot.

Each run: `requeue_orphans()` first sweeps any `mining_queue` row still
marked `'processing'` — since the flock guarantees a single live writer, any
such row belongs to a writer that died mid-job, not one currently running.
It's reset to `'pending'` (or straight to `'error'` if `attempts` already hit
`worker_max_attempts`) so a dead worker can never permanently wedge
curation (`enqueue_curate` refuses to enqueue while one `'curate'` job is
`'processing'`).

Then `drain()` claims up to `max_jobs=50` jobs, one at a time:

```sql
UPDATE mining_queue SET status = 'processing', attempts = attempts + 1
WHERE id = (SELECT id FROM mining_queue WHERE status = 'pending'
            AND next_attempt_at <= now() ORDER BY id LIMIT 1
            FOR UPDATE SKIP LOCKED)
RETURNING ...
```

`FOR UPDATE SKIP LOCKED` is defense-in-depth on top of the flock — even if
two writers somehow ran, they couldn't double-claim the same row. Each job
dispatches by `kind`: `mine` → `mining.mine_session()`, `embed` →
`store.reembed_document()`, `checkpoint_enrich` →
`continuity.enrich.enrich_checkpoint()`, `curate` → `curation.run_pass()`,
`backup` → `backup.run_backup()`. Maintenance is claimed first, checkpoint
enrichment second, and ordinary mining/embed work third. On success the row
becomes `'done'`. On failure,
`_fail()` rolls back the job's half-done writes and either reschedules with
exponential backoff (`worker_backoff_seconds * 2 ** (attempts - 1)`, default
base 300s) or, past `worker_max_attempts` (default 3), marks the row
`'error'` for a human to see in `rag status`/`rag review`.

After draining, the worker runs one bounded `curation.run_pass()` and an
**opportunistic backup** — `run_backup()` fires only if the newest local
`.dump` is more than 24 hours old, so the worker doesn't dump the database on
every single spawn. Every failure path — lock issues, a bad job, curation
throwing, backup failing — is caught, logged to
`~/.agentic-rag/log/worker.log`, and the process still exits `0`: **a worker
crash must never surface into a hook or a session.**

## Triggering work: provider lifecycle hooks

The legacy `rag install` wires three hooks into `~/.claude/settings.json`
(`agentic_rag/install.py`), each shelling out to a small stdlib-only module
under `agentic_rag/hooks/`:

| Hook | Matcher / timeout | DB role | Does | Failure mode |
|---|---|---|---|---|
| `SessionStart` | `startup\|resume\|clear\|compact`, 10s | `writer` | Injects every matching pin, the domain map, recent project-relevant documents, and any operational warnings (stale backup, queue errors); also enqueues a `curate` job if the last one is >24h old and spawns the worker if anything is due. | **Fail-closed, visibly** — on any exception it still emits `"⚠️ agentic-rag unavailable: <error>"` as context, so absence of memory is never silent. |
| `UserPromptSubmit` | (no matcher), 5s | `reader` | Regex-detects a *strong* error signature (traceback, `FooError:`, `file:line`, `panic`/`segfault`, ...), turns distinctive tokens into a sanitized OR-`tsquery`, and calls `recall_signals()` (English-only, `dtype='signal'` documents) plus a pin lookup. | **Silent on error** (logged, not surfaced) — precision over recall by design; a false warning on every prompt would be worse than an occasional missed recall. |
| `Stop` | (no matcher), 10s | `writer` | Debounced enqueue of the session transcript as a `mine` job (`jobs.enqueue_mine`: at most one open `mine` job per session, due `mine_debounce_seconds` — default 600s — in the future, carrying over `last_uuid` so the next drain only mines the delta), then fire-and-forget spawns the worker. | **Fail open, silent** — every error logged and swallowed; the hook always exits 0 and prints nothing. |

The explicit `rag install --codex` target writes six entries to
`~/.codex/hooks.json`, removing only owned handler commands and preserving
every foreign entry:

| Codex event | Matcher / timeout / context budget | Continuity behavior |
|---|---|---|
| `SessionStart` | `startup\|resume\|clear\|compact`, 10s, `additionalContextLimit=10000` | Injects ordinary memory context and a bounded checkpoint. The same-session checkpoint wins regardless of project metadata. Only when no same-session row exists may startup/resume fall back to the same canonical project; compact never falls back to another session or project. This is the only post-compaction restoration point. |
| `UserPromptSubmit` | 5s, `additionalContextLimit=5000` | Same deterministic signal/pin recall as the Claude integration. |
| `Stop` | 10s | Uses the shared transcript-delta path to enqueue debounced mining. |
| `PreCompact` | `manual\|auto`, 3s | Commits deterministic snapshot state, then best-effort captures repository state and queues asynchronous enrichment. No inline provider call. |
| `PostCompact` | `manual\|auto`, 3s | Marks the latest same-session checkpoint compacted. It cannot emit `additionalContext`; success is silent and failure is only a `systemMessage`. |
| `SessionEnd` | 3s | For `reason="other"`, uses the shared delta enqueue path to capture a final tail once. |

All handlers share one contract from `agentic_rag/hooks/common.py`: never block
the session. `spawn_worker()` launches `python -m agentic_rag.worker`
detached (`start_new_session=True`, stdio redirected to
`worker.log`) and is a no-op if a worker is already running — it relies on
the same flock, not on tracking whether it already spawned one.

Installation is an **idempotent merge**, not a file overwrite: `rag install`
reads the existing `~/.claude/settings.json`, strips only the hook entries
whose command contains the `agentic_rag.hooks.` marker (from each of the
three event lists), and appends fresh ones — any hook you or another tool
added stays untouched. A corrupt settings file aborts loudly rather than
being silently replaced; a valid one is backed up to `.json.bak` before every
write.

Codex installation is a separate recoverable transaction. It snapshots and
parses the three target files, probes only managed values in an ephemeral
`CODEX_HOME`, stages/validates every desired artifact, creates unique sibling
backups for existing changed files, and publishes only while the original file
identity still matches. A changing install records backup and installed-file
identities in a mode-`0600` rollback record. Restore verifies those identities
again and preserves concurrent destinations/recovery evidence rather than
overwriting. The user must inspect and trust changed handlers with `/hooks`;
the installer cannot grant trust.

## The two MCP servers

`agentic_rag/mcp_server.py` is a single `FastMCP` (stdio) app; which server
you get is decided entirely by one environment variable, checked once at
connect time:

```python
def _connect():
    cfg = load_config()
    role = "reader" if _readonly() else "writer"
    return cfg, db.connect(cfg, role=role)
```

`rag install` registers **both** servers, user-scope, via `claude mcp
add-json`:

- **`agentic-rag`** — read-write, for main sessions. Connects as
  `rag_writer`. Registers all 9 tools.
- **`agentic-rag-ro`** — same command and module, `RAG_READONLY=1` in its
  env. Connects as `rag_reader`. Registers only the 6 read tools — the write
  tools aren't merely disabled, they're never added to the server at all
  (`build_server(readonly=True)` skips the `WRITE_TOOLS` loop entirely). This
  is the server meant for subagents, allowlisted to `mcp__agentic-rag-ro__*`
  behind a privilege boundary the subagent definition enforces, backed by a
  privilege boundary the database enforces too — even a smuggled write call
  would still hit a role with no `INSERT` grant.

| Read tools (both servers) | Write tools (RW server only) |
|---|---|
| `memory_domains` | `memory_save` |
| `memory_search` | `memory_pin` |
| `memory_get` | `memory_unpin` |
| `memory_neighbors` | |
| `memory_path` | |
| `memory_timeline` | |

Every tool call opens and closes its own short-lived, role-scoped connection
— there's no connection pool and no persistent server-side state between
calls. The only non-SQL work any tool does is `memory_search`'s single
Ollama HTTP call to embed the query; nothing in the MCP process runs a model
in-process.

## Data flow

**Write path** — `rag save`, `memory_save`, the miner, and the migration
importer all fund into the same gateway and the same commit:

```
 rag save ───────┐
 MCP memory_save ┤
 mining.mine_*  ─┼──► save_document()  (one transaction, rag_writer)
 migrate import ─┘        strip secrets → validate domain → INSERT/UPDATE
                           documents → replace_chunks() [SECURITY DEFINER]
                           → embed (Ollama; fail-open → mining_queue embed)
                           → upsert edges → resolve dangling → INSERT audit_log
                                    │
                                    ▼
                     documents · chunks · edges · audit_log
```

**Read / search path** — degrades gracefully, never fails outright on a down
embedding model:

```
 rag search ─────┐
 MCP memory_search┼──► try_embed_texts()  [Ollama, fail-open]
                           │  (failure → qvec=NULL, warning "FTS only")
                           ▼
                     hybrid_search()  [SQL, RRF k=60]
                       vector top-50  ⊕  tsv_en top-50  ⊕  tsv_de top-50
                       (active documents only, optional domain filter)
                                    │
                                    ▼
                     ranked hits (+ warnings if degraded)
```

**Mining path** — a session becomes knowledge without you doing anything:

```
 Supported coding session ends
        │  Stop hook → jobs.enqueue_mine()  (debounced, ≤1 open job/session)
        ▼
 mining_queue (kind='mine', status='pending')
        │  spawn_worker()  (detached, no-op if one is already running)
        ▼
 worker.main()  ── flock(worker.lock) singleton ──► drain()
        │  claim_next()  [FOR UPDATE SKIP LOCKED, due jobs only]
        ▼
 mining.mine_session()  ── run_structured() ── configured Codex or Claude CLI
        │  near-duplicate gate on each candidate
        ▼
 save_document()  (same gateway as the write path)
        ▼
documents · chunks · edges · audit_log
```

**Continuity path** — captures usable state before any asynchronous provider
work and restores only at the hook boundary that accepts additional context:

```text
PreCompact
   │  capture_snapshot_seed() → audited upsert (fast deterministic state)
   │  capture_repository_state() → audited upsert (bounded Git/artifact refs)
   └─ enqueue checkpoint_enrich(after_cursor=predecessor_cursor) → worker
                           │
                           ▼
                  validate bounded schema/evidence
                           │
Codex compacts             └─► apply_enrichment() [optional]
   │
PostCompact ──► mark_compacted() [bookkeeping; no additional context]
   │
SessionStart(source="compact")
   └─ latest_for_session() → render_checkpoint(max_chars) → additionalContext
```

A provider-wide enrichment failure restores the claimed job to `pending`,
restores its attempt count, applies the configured provider backoff, records
sanitized health state, and stops the drain. The deterministic snapshot remains
available throughout. A later successful job enriches that same checkpoint and
clears provider health.

## Next →

[11 · Reference — CLI & MCP](11-reference-cli-and-mcp.md) — every CLI command
and flag, both MCP servers' tools, the key SQL functions, and exit codes.
