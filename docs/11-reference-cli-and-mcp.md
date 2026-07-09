# 11 · Reference — CLI & MCP

*What you'll learn: every `rag` CLI command and flag, the exit-code contract, the MCP tools exposed by the read-write and read-only servers, and the key SQL functions the whole system is built on. This chapter is exhaustive, not tutorial — for the guided tour see [03 · Quick start](03-quick-start.md) and [04 · Working with your memory](04-working-with-memory.md).*

## The `rag` CLI

All subcommands live in `agentic_rag/cli.py`, a thin `argparse` layer over the library. `rag <command> --help` always reflects the same definitions this table does.

### Database & install

| Command | Flags | What it does |
|---|---|---|
| `rag init-db` | — | Applies pending SQL migrations from `sql/`, creates the schema, seeds the `general` domain. Prints which migrations applied. |
| `rag install` | `--no-launchd` | Registers the two MCP servers (`agentic-rag`, `agentic-rag-ro`) user-scope, wires the three Claude Code hooks into `~/.claude/settings.json`, and installs the **backup** launchd job (macOS only, unless `--no-launchd`). Does **not** create the database — run `init-db` first. |

### Domains

| Command | Flags | What it does |
|---|---|---|
| `rag domain add <name>` | `--description` (default `""`) | Creates (or is a no-op on) the domain. |
| `rag domain list` | — | Lists every domain with its live document count and description. |

### Content

| Command | Flags | What it does |
|---|---|---|
| `rag save` | `--title` (required) · `--domain` (required) · `--dtype` (required) · `--body` · `--file <path>` · `--slug` · `--edge PREDICATE:SLUG` (repeatable) | Saves through `save_document()` — the one audited write gateway. Body comes from `--body` or from reading `--file`; if neither is given, the body is empty. `--slug` upserts: if a document with that slug already exists, this save updates it in place; otherwise the new document is created carrying that slug. `--edge` can be repeated to attach one or more typed edges (predicate:target-slug) in the same write. Prints `created`/`updated <slug> (N chunks, N edges)`; any secret-stripping or embedding-retry warning goes to stderr. |
| `rag get <id_or_slug>` | `--json` | Fetches one document by UUID or slug, plus its incoming and outgoing edges. Human-readable by default; `--json` for the raw structure. Exits 1 if not found. |
| `rag search <query>` | `--domain` · `-k <int>` (default `8`) · `--json` | Runs the same hybrid search the MCP tools use. Prints `score  slug  [domain/dtype]` per hit by default; `--json` for the full result plus any degrade warnings. |
| `rag status` | — | One-screen health check: document counts per domain/status, mining-queue counts per kind/status (plus any queue errors), last local backup timestamp (and a warning if it's stale), last curation run. |

### Pins

| Command | Flags | What it does |
|---|---|---|
| `rag pin add` | `--body` · `--document` · `--scope` (default `global`) · `--priority <int>` (default `100`) | Creates a pin — a standing rule or a pointer to a document — injected at every session start. |
| `rag pin list` | `--all` | Lists active pins by default; `--all` includes inactive ones. |
| `rag pin rm <pin_id>` | — | Deactivates a pin. Exits 1 if no such active pin. |
| `rag pin verify <pin_id>` | — | Marks a pin verified (confirms it's still true). Exits 1 if no such active pin. |

### Backup & maintenance

| Command | Flags | What it does |
|---|---|---|
| `rag backup` | `--install-launchd` | Runs `pg_dump -Fc` to a local dump (plus a cloud copy if configured), rotates old dumps. `--install-launchd` (macOS only) additionally installs the scheduled job; on Linux it prints a pointer to [`docs/deploy/scheduling-linux.md`](deploy/scheduling-linux.md) and exits 1. |
| `rag maintenance` | `--install-launchd` · `--verify-backup` (force the weekly restore-test now) · `--no-worker` (skip the worker drain tick) | The tiny, always-exit-0, single-flight maintenance tick: drains the mining queue, rotates logs, and — weekly, or on demand with `--verify-backup` — restore-tests the newest backup into an isolated scratch database. `--install-launchd` on macOS installs the job and returns immediately (it does not also run the tick that invocation); on Linux it prints the scheduling-doc pointer and exits 1 instead of installing anything. |
| `rag restore <dump>` | `--yes` | Restores a `pg_dump` file into the live database inside a single transaction. Refuses without `--yes` (exit 1). This is the deliberate, real recovery path — distinct from `maintenance`'s report-only restore-test. |

### Curation

| Command | Flags | What it does |
|---|---|---|
| `rag review` | — | Prints the curation report: duplicate candidates, dangling links, stale pins, mining suggestions, and mining-queue errors. Read-only. |
| `rag purge` | `--older-days <int>` (default `30`) · `--yes` | Permanently deletes `refuted` documents older than the cutoff, via the admin role. Refuses without `--yes` (exit 1). |

### Migration (llm-wiki import)

| Command | Flags | What it does |
|---|---|---|
| `rag migrate run` | `--source <path>` (default `~/.ultra-memory`) · `--yes` · `--dry-run` · `--limit <int>` · `--skip-backup` | Imports an llm-wiki store (a directory with `wiki/` and an optional `memory.db`) through the gateway. Refuses without `--yes` or `--dry-run`. A real run (not `--dry-run`) takes a pre-migration backup unless `--skip-backup`, requires Ollama/`bge-m3` reachable (exits 3 otherwise — the import embeds every chunk), and takes the same worker flock the background worker uses (exits 3 if the worker currently holds it). |
| `rag migrate classify` | — | Reads the current store and writes a domain-classification report (reader role; no writes). |
| `rag migrate apply-domains <report_tsv>` | `--yes` | Applies a classification report's domain assignments. Refuses without `--yes`. Takes the same worker flock as `migrate run`, since it writes too. |
| `rag migrate report` | `--golden <path>` | Produces the migration acceptance report, optionally scored against a golden set. Reader role; no writes. |

### Exit-code contract

`main()` maps every code path to one of four exit codes:

| Code | Meaning | Raised by |
|---|---|---|
| `0` | OK | Successful completion of any command. |
| `1` | User or data error | Explicit refusals (missing `--yes`), not-found lookups, `ValueError`/`FileNotFoundError`. |
| `3` | Infrastructure error | `psycopg.OperationalError` (DB unreachable), `RuntimeError` (e.g. Ollama down during migration, worker lock held). |
| `4` | Unexpected error | Anything else — caught, printed as `unexpected error: <type>: <message>`, never a raw traceback. |

`argparse` itself exits `2` for malformed invocations (missing a required flag, unknown subcommand) — that's argparse's own contract, before any of this code runs.

## MCP servers

`rag install` registers two MCP servers, both defined in `agentic_rag/mcp_server.py`, both stdio-based, both doing SQL plus at most one Ollama HTTP call — never a model in-process:

- **`agentic-rag`** — read-write. Used by your main Claude Code sessions.
- **`agentic-rag-ro`** — read-only. Runs with `RAG_READONLY=1`, connects as `rag_reader`, and the write tools aren't registered at all — not just permission-denied at call time. Meant for subagents you want on the read side of a privilege boundary: allowlist only `mcp__agentic-rag-ro__*` tools in a subagent's own definition to enforce it.

### Read tools (both servers)

| Tool | Signature | What it does |
|---|---|---|
| `memory_domains` | `()` | Every domain with its description and document count. |
| `memory_search` | `(query, domain=None, k=8)` | Hybrid search (vector + full-text EN/DE, RRF fusion). Returns snippets with slug/score/verified_at. |
| `memory_get` | `(id_or_slug)` | Full document (title, body, meta, provenance, status) plus incoming and outgoing edges. |
| `memory_neighbors` | `(id_or_slug, depth=1, predicates=None)` | Every edge within `depth` hops (undirected, capped at 3), optionally filtered by predicate. |
| `memory_path` | `(from_id_or_slug, to_id_or_slug, max_depth=4)` | Shortest edge path between two documents; empty steps means no connection within `max_depth`. |
| `memory_timeline` | `(id_or_slug)` | Every edge touching the document, ordered by validity interval. |

### Write tools (`agentic-rag` only)

| Tool | Signature | What it does |
|---|---|---|
| `memory_save` | `(title, body, domain, dtype="memory", slug=None, doc_id=None, edges=None, mark_verified=False)` | Saves through the same gateway as `rag save`. Pass `doc_id` to update an existing document; set `mark_verified=true` when the user corrects or confirms stored knowledge. `edges` is a list of `{predicate, dst_slug, evidence?, confidence?}`. |
| `memory_pin` | `(body=None, document_id=None, scope="global", priority=100)` | Pins a rule or document for every future session start. User-owned — call only on the user's explicit instruction. |
| `memory_unpin` | `(pin_id)` | Deactivates a pin. Same rule: only on explicit instruction. |

## Key SQL functions

| Function | File | Signature | Purpose |
|---|---|---|---|
| `hybrid_search` | `sql/003_search.sql` | `(query_text text, query_vec halfvec(1024) DEFAULT NULL, p_domain text DEFAULT NULL, k int DEFAULT 8) RETURNS TABLE(document_id, chunk_id, title, slug, domain, dtype, snippet, score, verified_at, provenance)` | Deterministic hybrid search: vector cosine, English `ts_rank_cd`, and German `ts_rank_cd` each produce an independent top-50 ranked list; all three are fused with Reciprocal Rank Fusion (`Σ 1/(60 + rank)`) and returned as one list of `k` rows, ordered by fused score then slug. `LANGUAGE sql STABLE`. |
| `replace_chunks` | `sql/002_roles.sql` | `(p_document_id uuid, p_contents text[], p_embeddings text[]) RETURNS int` | The only way `rag_writer` can delete a row from `chunks` — `SECURITY DEFINER`, runs as the table owner, deletes and re-inserts chunks for exactly the one `p_document_id` passed in. Granted to `rag_writer` and `rag_admin`; revoked from `PUBLIC`. This is what makes chunk regeneration on edit possible without giving the writer role any table-wide `DELETE`. |
| `graph_neighbors` | `sql/004_graph.sql` | `(p_id uuid, p_depth int DEFAULT 1, p_predicates text[] DEFAULT NULL) RETURNS TABLE(edge_id, src_id, dst_id, predicate, evidence, confidence, depth)` | Undirected BFS over `edges` up to `p_depth` hops (capped at 3 by the caller), cycle-safe per branch, optionally filtered to a `predicates` allowlist. Backs the `memory_neighbors` MCP tool. `LANGUAGE sql STABLE`. |
| `graph_path` | `sql/004_graph.sql` | `(p_from uuid, p_to uuid, p_max_depth int DEFAULT 4) RETURNS TABLE(step int, doc_id uuid, via_predicate text)` | Shortest undirected path between two documents via a recursive CTE that generates shorter paths first; empty result means no connection within `p_max_depth`. Backs the `memory_path` MCP tool. `LANGUAGE sql STABLE`. |
| `graph_timeline` | `sql/004_graph.sql` | `(p_id uuid) RETURNS TABLE(edge_id, src_slug, dst_slug, predicate, valid_from, valid_to)` | Every edge touching a document (either side), ordered by `valid_from` — the bi-temporal view. Backs the `memory_timeline` MCP tool. `LANGUAGE sql STABLE`. |
| `recall_signals` | `sql/005_plan2.sql` | `(q_or text, k int DEFAULT 3) RETURNS TABLE(slug, title, verified_at, created_at, score)` | English full-text recall over active `dtype='signal'` documents only, ranked by `ts_rank_cd` against a sanitized OR-`tsquery` string. Backs the `UserPromptSubmit` hook's prompt-time signal recall (not an MCP tool). `LANGUAGE sql STABLE`. |

See [10 · Architecture](10-architecture.md) for how these fit into the schema and role matrix, and [07 · Privacy, cost & control](07-privacy-and-cost.md) for the destruction-protection reasoning.

## Next →

[12 · Contributing](12-contributing.md) — dev setup, running the test suite, the doc-reminder git hook, and code layout.
