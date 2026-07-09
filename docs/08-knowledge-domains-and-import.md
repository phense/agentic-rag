# Knowledge domains & import

*What you'll learn: what a domain actually is (a map, not a taxonomy),
managing domains with `rag domain`, and the full workflow for importing an
existing llm-wiki store — `wiki/` + optional `memory.db` — with `rag
migrate`.*

## Domains are a map, not a taxonomy

A domain is not a folder your documents live inside, and it's not a tag
cloud. It's one row in a `domains` table (`name`, `description`), and every
document has exactly one — a foreign key, not a list. Think of a domain as
the answer to "where would I look for this?" rather than "what is this?".
Keep the set small: a handful of domains that map to how you actually think
about your own knowledge beats dozens of narrow ones.

`rag init-db` seeds one domain for you automatically: **`general`**
("Uncategorized knowledge"). It always exists, so a fresh install can `rag
save` before you've defined anything else — you're never blocked on picking
a taxonomy before you can write your first document.

## Managing domains

```bash
rag domain add cooking --description "Recipes and kitchen notes"
rag domain add home-lab --description "Self-hosting and networking notes"
```

`rag domain add <name> [--description TEXT]` is idempotent — re-running it
with a new `--description` updates that domain's description in place; it
never fails just because the domain already exists. Domain names have no
enforced format (unlike domains created by `migrate classify`, below, which
are constrained to kebab-case — see [Importing an existing llm-wiki
store](#importing-an-existing-llm-wiki-store)).

```bash
rag domain list
```

```
cooking                 12  Recipes and kitchen notes
general                  3  Uncategorized knowledge
home-lab                  8  Self-hosting and networking notes
```

The count is live active-document count per domain, not a cached number.

There's no `rag domain rm` — domains aren't deleted, only added to or
described differently. To move a document to a different domain, you save
over it with a new domain, or (for a batch of documents) use `rag migrate
apply-domains`, described next. Under the hood both paths update a single
column on `documents` — moving a document between domains never touches its
chunks or embeddings.

## Importing an existing llm-wiki store

If you already keep notes in an **llm-wiki**-style store — a topic-partitioned
folder of Markdown pages under `wiki/`, with an optional `memory.db` SQLite
database alongside it — `rag migrate` imports that store through the same
write gateway every other save goes through. It's a one-shot, resumable
operation with three guarantees worth knowing up front:

- **The source is never written.** Wiki pages are only ever read; if a
  `memory.db` is present, it's opened with a read-only SQLite URI
  (`mode=ro`). Nothing about this import can touch your original store.
- **Imports are idempotent by provenance.** Each imported document carries
  a `source_id` in its `provenance` (the wiki page's relative path, or the
  memory row's id). Re-running `migrate run` against the same source skips
  everything already imported — safe to re-run after adding new pages, or
  after a partial run.
- **`memory.db` is optional.** A `wiki/` directory is required (the command
  fails immediately if it's missing); `memory.db` is only read if it
  exists. A wiki-only store imports fine.

### The flow

Five subcommands, run in this order:

| Step | Command | What it does | Writes to your DB? |
|---|---|---|---|
| 1 | `rag migrate run --dry-run` | Preview: scans the source, reports counts and warnings | No |
| 2 | `rag migrate run --yes` | Actually imports | Yes |
| 3 | `rag migrate classify` | LLM proposes domain re-assignments for the imported docs | No (writes report files only) |
| 4 | `rag migrate apply-domains <report> --yes` | Applies the moves you approved | Yes |
| 5 | `rag migrate report` | Builds an acceptance report over the whole import | No |

**1. Preview with `--dry-run`.**

```bash
rag migrate run --source ~/my-wiki --dry-run
```

This scans the source and prints a breakdown by domain/type/status, plus
any parsing warnings (unknown frontmatter, duplicate slugs, and so on) —
without writing anything:

```
source scan: 128 wiki pages, 40 memories (12 pinned, 9 signal sections)
      5  cooking         concept    active
      3  cooking         index      archived
     28  home-lab        concept    active
      ...
imported: 0 docs (+0 signal children), skipped (already imported): 0
domains created: —
```

If you omit `--source`, it defaults to `~/.ultra-memory`; point it at
whatever directory holds your `wiki/` (and optional `memory.db`) instead.

**2. Run it for real with `--yes`.**

```bash
rag migrate run --source ~/my-wiki --yes
```

Before writing anything, this takes a pre-migration backup automatically
(skip it with `--skip-backup`, though there's little reason to) and checks
that Ollama/`bge-m3` is reachable — the import embeds every chunk it
creates, so it refuses outright rather than importing thousands of documents
without embeddings. It also takes the same single-writer lock the
background worker uses, so it won't race a mining run in progress; if the
worker holds the lock, it tells you to retry in a moment rather than
corrupting anything. Use `--limit N` to import only the first N new
documents — handy for a small trial run before committing to the whole
corpus.

Each new document is saved through the normal write gateway, so it gets
chunked, embedded, secret-stripped, and audit-logged exactly like a `rag
save`. A closing summary reports what happened:

```
imported: 1780 docs (+9 signal children), skipped (already imported): 0
pins: 12 created, 0 skipped
edges written: 640
redactions: 3 in 2 docs
saved without embedding (queued): 0
domains created: cooking, home-lab
slug conflicts (renamed): 0
```

**3. Ask the LLM to sanity-check domains with `classify`.**

Domains created by an import come from wherever the source's own topic
structure put things (see [Where import domains come from](#where-import-domains-come-from),
below) — reasonable defaults, but not necessarily the domains you'd have
chosen by hand, and a wiki that grew organically over time can end up
scattered.

```bash
rag migrate classify
```

This only looks at documents from this import (it never touches documents
you saved directly with `rag save`). It's read-only against your database —
it writes two files under `~/.agentic-rag/migration/` and nothing else:
`domain-report.tsv` (one row per document: `slug`, current domain, proposed
domain) and `domain-report.md`, a human-readable summary of the proposed
moves and any newly proposed domains. The classifier runs on whatever your
local `claude` CLI is authenticated with (your Claude subscription or an API
key) and is instructed to strongly prefer
reusing your existing domains — it only proposes a brand-new domain when no
existing one fits and the new one would plausibly hold at least 15
documents.

**4. Review, then apply.**

`classify` proposes; it never applies anything by itself. Open
`domain-report.tsv`, delete any rows whose proposed move you don't want
(the `proposed` column is exactly what gets applied), and create any
approved new domains first — `apply-domains` refuses if a proposed domain
doesn't exist yet:

```bash
rag domain add baking --description "Bread and pastry-specific notes"
rag migrate apply-domains ~/.agentic-rag/migration/domain-report.tsv --yes
```

```
domains applied: 212, skipped: 8
```

Rows are skipped when the document is already in its proposed domain (this
makes a second run of the same report a safe no-op) or when a slug in the
report no longer resolves to a document.

**5. Build the acceptance report.**

```bash
rag migrate report
```

```
report: ~/.agentic-rag/migration/acceptance-report.md
```

This one Markdown file rolls up the whole import: document counts by type
and status, domain breakdown, edge counts (including any dangling links,
with their top targets — memory-store session-event links are deliberately
not imported, so don't expect those to show up here), imported pins, the
cumulative run stats from every
`migrate run` you've done (including a redaction count worth eyeballing —
the credential-pattern matcher can over-redact), and a deterministic
10-document spot-check sample to read by hand. Pass `--golden
your-queries.tsv` (a two-column file: `query`, tab, `expected_slug`) to add
a hit-rate check against a set of queries you know the answer to — useful
for confirming search quality survived the move, but entirely optional.

### Where import domains come from

Domains aren't configured before an import — they're **derived** from the
source itself:

- For wiki pages, the domain is the top-level topic directory under `wiki/`,
  slugified. A page at `wiki/cooking/sourdough-starter.md` gets domain
  `cooking`. Pages directly at the root of `wiki/` (no topic directory) fall
  back to `general`.
- For `memory.db` rows, the domain is the row's `topic` column, slugified,
  falling back to `general` if it's empty.

Any domain name the source needs that doesn't already exist is created
automatically during `migrate run` (with an empty description, listed under
"domains created" in the summary above) — and one that already exists is
left alone; the import never overwrites a description you already wrote.
That's what step 3 (`classify`) is for: consolidating the domains an import
happens to produce into the set you actually want.

## Next →

[09 · Maintenance & backups](09-maintenance-and-backups.md) — `rag backup`
and `rag maintenance` (the same pre-migration backup this chapter leans on),
restore-testing, and scheduling on macOS and Linux.
