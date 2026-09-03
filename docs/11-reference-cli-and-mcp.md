# 11 · Reference — CLI & MCP

*What you'll learn: every `rag` CLI command and flag, the exit-code contract, the MCP tools exposed by the read-write and read-only servers, and the key SQL functions the whole system is built on. This chapter is exhaustive, not tutorial — for the guided tour see [03 · Quick start](03-quick-start.md) and [04 · Working with your memory](04-working-with-memory.md).*

## The `rag` CLI

All subcommands live in `agentic_rag/cli.py`, a thin `argparse` layer over the library. `rag <command> --help` always reflects the same definitions this table does.

### Database & install

| Command | Flags | What it does |
|---|---|---|
| `rag init-db` | — | Applies pending SQL migrations from `sql/`, creates the schema, seeds the `general` domain. Prints which migrations applied. |
| `rag install` | `--no-launchd` · `--codex` · `--check` · `--restore <ROLLBACK_RECORD>` | With no target flag, registers the two Claude MCP servers, merges six Claude hooks plus `autoCompactWindow = 500000` into `~/.claude/settings.json` (unique `settings.json.bak.<id>` backup, mode-0600 rollback record, printed restore command), and installs the macOS backup job unless skipped. `--codex` instead manages only Codex config/hooks/prompt and never registers Claude MCP or another scheduler. `--check` previews either target and writes nothing (for Claude: no MCP registration, no launchd). `--restore` is mutually exclusive with `--check`, accepts a Claude or Codex record, and dispatches on the record's target: `--codex --restore` still works for Codex records; a Claude record with `--codex` is refused. Does **not** create the database. |

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
| `rag status` | — | One-screen health check: document counts; queue counts/errors and oldest open mine; provider health/remediation; open checkpoint count; newest checkpoint time/quality/project; pending checkpoint-enrichment count/age/warnings; backup freshness; and last curation run. |
| `rag queue requeue-legacy-provider-failures` | `--expect <int>` (default `60`) · `--yes` | One-time recovery for the exact legacy Claude missing-binary/exit-1 cohort. Always prints the candidate count; refuses without `--yes` or on count mismatch. Preserves job identity, payload, transcript cursor/path, resets attempts, and makes only that cohort pending. |

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

### Claude install, check, and restore

```bash
rag install --check
rag install
rag install --restore /absolute/path/to/claude-rollback-<id>.json
```

Check/install output prints the managed value (`managed:
autoCompactWindow=500000`), the `would change:`/`changed:` settings path (or
`Claude settings: already up to date`), the `backup:` line for a changing
install, and any `warning:` lines — no `model` or one without the `[1m]`
suffix (the window is capped to the model's own), `autoCompactEnabled=false`,
or `CLAUDE_CODE_AUTO_COMPACT_WINDOW` / `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` /
`DISABLE_AUTO_COMPACT` / `DISABLE_COMPACT` in the settings `env` block or the
process environment. Check mode ends with `check complete: no files written;
MCP and launchd untouched`. A real install continues with the `mcp:`,
`hooks:` (review with `/hooks`), `autocompact:` (verify with `/autocompact`,
expect 500000 tokens from settings), and `launchd:` lines and, when the file
changed, the exact `rollback: rag install --restore <record>` command.

The record lives under `~/.agentic-rag/state/claude-rollback-<id>.json`
(mode 0600) and names the settings path, the unique sibling backup
`settings.json.bak.<32 hex>`, and both file identities. Restore verifies those
identities, refuses a backup or target that changed since the install, prints
each restored path and `rollback complete`. Claude Code reloads hook edits
live; MCP registration is untouched by restore.

### Codex install, check, and restore

```bash
rag install --codex --check
rag install --codex
rag install --codex --restore /absolute/path/to/codex-rollback-<id>.json
```

Check/install output enumerates the managed policy settings, including
`model_context_window=600000`,
`model_auto_compact_token_limit=500000`, total-token scope, hooks/memories,
and Luna memory models. Separately, its would-change/changed paths report the
managed prompt artifact path along with config and hooks paths. It also reports
unique sibling backups, foreign `herdr-agent-state.sh` duplicate counts, Codex
version when available, runtime-validation coverage, isolated-probe guarantees,
and the required `/hooks` trust review. Check mode ends with “no files written.”

A changing install prints an exact rollback command whose record normally
lives under `~/.agentic-rag/state/`. Restore prints each restored path and
`rollback complete`. It authenticates both the rollback backup bytes and the
installed target identities; conflicts abort without overwriting concurrent
content and retain named recovery evidence.

`--codex-home <path>` also exists as a deliberately hidden test/rollout flag.
With `--check` it allows an explicit temporary home to exercise the full plan
and isolated Codex probe without touching the real `~/.codex`. It cannot be
combined with `--restore`, because restore obtains its target home from the
validated rollback record.

### Claude hook output contract

| Event | Observable result |
|---|---|
| `PreCompact` | Exit 0, always. Persists the checkpoint, then writes the versioned compact instructions (`assets/claude/compact_prompt.md`, `Version: 1.0`) plus `agentic-rag checkpoint: <id>` to **stdout**; Claude appends that stdout to its compaction prompt. The prompt is printed even when the database step failed; the hook never exits 2. |
| `PostCompact` | Silent on success. Matches the newest same-session/same-trigger `PreCompact` checkpoint without a `turn_id` (compacted or not — the newest compaction wins), marks it compacted, and stores the payload's `compact_summary` as the bounded, secret-stripped handoff (`handoff_max_chars`, default 8,000). Never emits `additionalContext`; no match is a no-op; a DB failure emits only `{"systemMessage":"checkpoint bookkeeping delayed"}`. |
| `SessionStart(source="compact")` | Emits the same-session checkpoint, including the `Handoff (Claude compact summary, CURRENT|HISTORICAL, age=…h)` section, as `additionalContext`. The whole output is capped at `context_max_chars` (default 9,500; Claude discards per-hook context above 10,000 characters) and starts with a `⚠️ context truncated …` warning when anything was cut. Same selection rules as Codex; compact never falls back to another session or project. |
| `SessionEnd` | Silent delta enqueue for every reason (`clear`, `resume`, `logout`, `prompt_input_exit`, `other`) through the same deduplicating path as `Stop`. Installed with `timeout: 1`; Claude allows 1.5 s for all SessionEnd hooks together, and `Stop` is the guaranteed path if the budget is overrun. |

### Codex hook output contract

| Event | Observable result |
|---|---|
| `PreCompact` | Silent, always exit 0; snapshot persistence/enqueue failures are logged and never block compaction. |
| `PostCompact` | Silent on success. It cannot inject context; a DB failure may emit only `{"systemMessage":"checkpoint bookkeeping delayed"}`. |
| `SessionStart(source="compact")` | Emits the same-session bounded checkpoint as `additionalContext` before the next model request. Same-session lookup wins regardless of project metadata. Startup/resume alone may fall back within the same canonical project; compact never falls back to another session or project. This is the restoration event. |
| `SessionEnd(reason="other")` | Silent delta enqueue through the same deduplicating path as `Stop`. |

After any Codex install, run `/hooks`, inspect the six owned commands/hashes,
and trust only those you recognize. Installation writes configuration but does
not make the trust decision.

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
