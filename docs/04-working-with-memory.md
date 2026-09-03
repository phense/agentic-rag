# Working with your memory

*What you'll learn: the everyday commands — `rag save`, `rag get`, `rag search`, `rag pin`, `rag status` — how domains fit in, and the MCP tools Claude itself uses inside a session, including the read-only boundary subagents run behind.*

Most of what lands in agentic-rag gets there on its own, via session mining (the next chapter). This chapter is about the other path: you, or Claude acting on your behalf, reading and writing memory directly — from a terminal with the `rag` CLI, or from inside a Claude Code session via MCP tools.

## The CLI

Every `rag` subcommand connects to Postgres with a role scoped to what it needs (`rag_reader` for reads, `rag_writer` for writes) and prints plain text by default; most read commands also take `--json` for scripting.

### `rag save` — write a document

```
rag save --title TITLE --domain DOMAIN --dtype DTYPE [--body TEXT | --file PATH]
          [--slug SLUG] [--edge PREDICATE:SLUG ...]
```

| Flag | Required | Notes |
|---|---|---|
| `--title` | yes | document title |
| `--domain` | yes | must be an existing domain (`rag domain add` first) |
| `--dtype` | yes | one of `concept`, `lesson`, `signal`, `source`, `synthesis`, `memory`, `reference`, `index` |
| `--body` | one of `--body`/`--file` | inline body text |
| `--file` | one of `--body`/`--file` | read the body from a file |
| `--slug` | no | **upsert**: updates the document at this slug if it exists, otherwise creates it with this slug |
| `--edge` | no, repeatable | `PREDICATE:SLUG` — creates a typed edge to another document by slug |

```
$ rag save --title "Connection pool exhausts under N workers" \
    --domain infra --dtype lesson \
    --body "Raising max_workers past pool_size silently queues connections; symptom is rising p99 with no errors. Fix: max_workers <= pool_size - reserved."
created infra-connection-pool-exhausts-under-n-workers (3 chunks, 0 edges)
```

Every write goes through the same gateway regardless of caller (CLI, MCP, mining, migration): it strips anything secret-shaped out of title/body/meta first, chunks and embeds the body, resolves any `--edge` targets (dangling ones are still recorded, by slug, and resolved later if the target shows up), and writes an audit row — all in one transaction. If Ollama is unreachable, the save still succeeds and prints a `WARNING`; the missing embedding is queued for a retry instead of blocking you.

Edge predicates are a fixed vocabulary: `references`, `extends`, `depends_on`, `complements`, `contrasts_with`, `informs`, `part_of`, `derived_from`, `supersedes`, `contradicts`, `duplicate_of`. Anything else is rejected at the database.

```
$ rag save --title "Pool sizing guide" --domain infra --dtype concept \
    --file pool-sizing.md \
    --edge extends:infra-connection-pool-exhausts-under-n-workers
created infra-pool-sizing-guide (5 chunks, 1 edges)
```

To correct or extend a document later, pass its slug back with `--slug` — same content model, no new document:

```
$ rag save --slug infra-connection-pool-exhausts-under-n-workers \
    --title "Connection pool exhausts under N workers" --domain infra --dtype lesson \
    --body "…same as above, plus: this also shows up as connection timeouts under load balancers with aggressive health checks."
updated infra-connection-pool-exhausts-under-n-workers (4 chunks, 0 edges)
```

### `rag get` — read a document back

```
$ rag get infra-connection-pool-exhausts-under-n-workers
# Connection pool exhausts under N workers  [infra/lesson · active · infra-connection-pool-exhausts-under-n-workers]

Raising max_workers past pool_size silently queues connections; …
  <- extends: infra-pool-sizing-guide
```

`rag get ID_OR_SLUG` accepts either the slug or the document's UUID. Add `--json` for the full record (title, body, `meta`, `provenance`, `status`, timestamps, and both `edges_out`/`edges_in` with `predicate`/`peer_slug`/`evidence`/`confidence`) — useful for piping into other tools or inspecting provenance.

### `rag search` — hybrid retrieval

```
rag search QUERY [--domain DOMAIN] [-k N] [--json]
```

Search blends multilingual vector similarity (`bge-m3`, any language) with English/German keyword full-text into one ranked list; `-k` caps how many hits come back (default 8). If Ollama is down, search degrades to full-text-only and says so in a warning rather than failing outright.

```
$ rag search "connection pool exhaustion" --domain infra -k 5
0.8421  infra-connection-pool-exhausts-under-n-workers [infra/lesson]
0.7103  infra-pool-sizing-guide            [infra/concept]
```

`--json` returns `{"results": [...], "warnings": [...]}`, one object per hit with `slug`, `domain`, `dtype`, `score`, `snippet`, `verified_at`, and `provenance`.

### `rag pin` — standing rules

Pins are short, user-owned rules or document references injected at the start of every session. They're never created or changed automatically — only you (CLI) or Claude acting on your explicit instruction (MCP) can write one.

```
rag pin add [--body TEXT] [--document DOC_ID] [--scope SCOPE] [--priority N]
rag pin list [--all]
rag pin rm PIN_ID
rag pin verify PIN_ID
```

- `--scope` is `global` (default, injected everywhere), an absolute project path (injected only for sessions in that directory or a subdirectory of it), or the name of an existing domain (domain-scoped pins aren't auto-injected at session start — no domain is knowable from a working directory — but they do show up in `rag pin list` and the `rag review` report).
- `--priority` (default `100`) sets injection order — lower first, then by creation time.
- If you pass `--document` without `--body`, the pin body is generated for you as `[[slug]] — title`.
- **Never put credentials or other secrets in a pin.** Matching global and
  path-scoped pin bodies can be included in session-mining provider prompts.
  They are not independently secret-stripped at that boundary today; the
  defense-in-depth fix is tracked in root backlog 0.0.
- `rag pin rm` deactivates the pin (`active = false`); it isn't deleted. `rag pin verify` stamps `last_verified`, resetting the staleness clock a pin is measured against.

```
$ rag pin add --body "Run the test suite with --maxfail=1 in this repo" --scope /Users/example/project
pinned 3f9a2e7e-...

$ rag pin list
3f9a2e7e-...  [/Users/example/project] p100  Run the test suite with --maxfail=1 in this repo
```

### Domains — where to look

A domain is just a name, a description, and a live document count — metadata that tells you and Claude where to search, not a schema partition. `general` always exists (seeded by `rag init-db`); everything else you define.

```
$ rag domain add infra --description "Backend infrastructure and ops lessons"
domain 'infra' ready

$ rag domain list
general              12  Uncategorized knowledge
infra                 4  Backend infrastructure and ops lessons
```

`--domain` is required on `rag save` and optional (as a filter) on `rag search`. Growing and reorganizing domains — including deriving them automatically from an import — is covered in [08 · Knowledge domains & import](08-knowledge-domains-and-import.md).

### `rag status` — a health check at a glance

```
$ rag status
documents:
  general              active     12
  infra                 active      4
queue:
  mine                  done       31
  mine                  pending     2
last local backup: agentic-rag-2026-07-08T030000.dump
last curation: 2026-07-08 03:05
```

It reports live document counts per domain/status, the mining queue by kind/status (plus any queue entries stuck in `error`, with their last error message), the newest local backup file, a backup warning if one is outstanding, and the timestamp of the last curation pass. It's the same data the SessionStart hook uses to decide what's worth surfacing.

## Inside a Claude Code session: the MCP tools

`rag install` registers two MCP servers, user-scoped, so they're available in every project:

- **`agentic-rag`** — read-write, wired into your main session.
- **`agentic-rag-ro`** — read-only, wired into subagents. Not a permission flag: it's built from a smaller tool set entirely (`RAG_READONLY=1`, connected as `rag_reader`), so write tools don't exist to be called from a subagent context in the first place. As defense in depth, subagent definitions should also allowlist only `mcp__agentic-rag-ro__*` tools.

### Read tools (on both servers)

| Tool | What it does |
|---|---|
| `memory_domains` | list every domain with description and document count |
| `memory_search(query, domain?, k?)` | the same hybrid search as `rag search` |
| `memory_get(id_or_slug)` | full document plus its incoming/outgoing edges |
| `memory_neighbors(id_or_slug, depth?, predicates?)` | graph traversal — every edge within N hops |
| `memory_path(from_id_or_slug, to_id_or_slug, max_depth?)` | shortest edge path between two documents |
| `memory_timeline(id_or_slug)` | every edge touching a document, ordered by validity interval |

In a main session these are `mcp__agentic-rag__memory_search` etc.; for a subagent they're `mcp__agentic-rag-ro__memory_search` etc. — same names, same behavior, different (read-only) connection underneath.

### Write tools (read-write server only)

| Tool | What it does |
|---|---|
| `memory_save(title, body, domain, dtype?, slug?, doc_id?, edges?, mark_verified?)` | save through the same gateway as `rag save`; pass `doc_id` to update an existing document, and `mark_verified=true` when the user corrects or confirms something so `verified_at` gets stamped |
| `memory_pin(body?, document_id?, scope?, priority?)` | add a pin — Claude is only supposed to call this on your explicit instruction, never on its own initiative |
| `memory_unpin(pin_id)` | deactivate a pin — same rule: only on your explicit instruction |

`memory_save`'s `edges` argument is a list of `{predicate, dst_slug, evidence?, confidence?}` objects using the same fixed predicate vocabulary as `rag save --edge`.

In practice, inside a session this mostly happens without you typing a `rag` command at all: Claude calls `memory_search`/`memory_get` to check what it already knows before answering, and `memory_save` when something durable is worth keeping — the same write gateway, the same domains, the same edges, just invoked as a tool call instead of a shell command.

## Next →

[05 · Session mining & curation](05-session-mining-and-curation.md) — how your Claude sessions become durable knowledge on their own, and how the store curates itself afterward.
