# agentic-rag

### Provider-neutral long-term memory and compaction continuity — in a real database.

**Coding sessions end and long contexts compact. agentic-rag preserves both:
a canonical, searchable knowledge base in local PostgreSQL + pgvector, plus
bounded checkpoints that let Codex resume after compaction. Hybrid vector +
full-text search, lifecycle hooks, and a provider CLI you control — without a
hosted RAG service.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-0.1.0-informational.svg)](pyproject.toml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](pyproject.toml)
[![PostgreSQL + pgvector](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg)](https://github.com/pgvector/pgvector)

Most "RAG memory" tools are a cloud retrieval layer you feed documents to:
you push, you query, you pay per call. agentic-rag flips both halves. It stores
knowledge in **local Postgres + pgvector** — real HNSW
approximate-nearest-neighbour search blended with bilingual full-text — and it
**populates itself from supported coding sessions**. It also stores compact,
audited continuation checkpoints at Codex compaction boundaries.

Every content write funnels through **one gateway**: it strips secret-shaped
tokens, chunks and embeds the text with a local model, resolves the document's
links into a **typed knowledge graph**, and logs the change — all in one
transaction. When a session ends, a single-writer worker uses the configured
Codex or Claude CLI to turn the bounded transcript digest into durable,
findable memories. The core data model and provider seam are provider-neutral;
integrations adapt each coding agent's lifecycle and output contracts.

It runs on your machine and uses **your configured CLI account** for
LLM-assisted mining, curation, and bounded checkpoint enrichment: Codex with
ChatGPT login or Claude with its supported OAuth or API-key authentication.
Embeddings are **always local** (Ollama), so retrieval does not call either
provider. It's RAM-lean by design: no always-on daemon beyond Postgres and
Ollama, and an idle footprint near zero between sessions. And it's built
data-safety-first — it archives rather than deletes, writes through a
least-privilege role matrix, audits every change, and periodically
restore-tests its own backups.

> **Your data stays yours.** This repository is **code only** — it ships no
> content. Your documents, embeddings, links, and any secrets live in *your*
> PostgreSQL database on *your* machine; nothing leaves it unless you explicitly
> configure a synced backup directory. LLM-assisted mining, curation, and
> checkpoint enrichment send bounded, redacted inputs through the configured
> local Codex or Claude CLI; agentic-rag has no separate hosted RAG backend.

**[Why](#why-agentic-rag)** · **[Quick start](#quick-start)** · **[What's different](#what-makes-it-different)** · **[How it works](#how-it-works)** · **[Comparison](#comparison)** · **[Configuration](#configuration)** · **[📖 Handbook](#-documentation--handbook)** · **[Status](#status)** · **[Acknowledgments](#acknowledgments)** · **[License](#license)**

---

## Why agentic-rag

🔎 **Hybrid search that actually ranks.** Vector ANN over `pgvector` (HNSW, cosine) — multilingual by way of `bge-m3` embeddings — blended with GIN keyword full-text into one ranked query. Search in **any language**; not a file scan, not lexical-only.

🌱 **It turns sessions into durable knowledge and continuation state.** Mining
uses your configured Codex or Claude CLI. On Codex, `PreCompact` also captures
a fast checkpoint so `SessionStart(source="compact")` can restore the goal,
blockers, next action, repository state, and evidence references.

♻️ **It curates itself.** A near-duplicate gate stops the store from bloating; `rag review` surfaces duplicates, dangling links, and stale pins; refuting a fact **archives** it (with a reason and evidence), never hard-deletes it.

🔒 **Local-first, on your own account.** Canonical knowledge and checkpoints
live in your Postgres. LLM-assisted work runs through the local Codex or Claude
CLI you configured. Embeddings are always local (Ollama), so search and
retrieval do not call either provider.

⚡ **RAM-lean.** A single-writer worker (flock singleton), no long-lived daemon of its own. Between sessions the footprint is essentially Postgres + Ollama idling — nothing else.

---

## Quick start

agentic-rag is a `rag` command-line tool with provider integrations. The legacy
no-option install wires two MCP servers and hooks into Claude Code; the explicit
Codex target installs continuity configuration and hooks.

**Prerequisites:**

- **PostgreSQL 17** with the [`pgvector`](https://github.com/pgvector/pgvector) extension (the schema uses `halfvec`, pgvector ≥ 0.7).
- **[Ollama](https://ollama.com)** with the embedding model pulled — `ollama pull bge-m3` (1024-dim, fixed to the schema).
- An authenticated LLM CLI: **Codex** (`codex login`) or **Claude** (`claude -p`). Claude/Haiku remains the package default for compatibility; select the provider in `[llm]`.
- **[`uv`](https://docs.astral.sh/uv/)** and **Python ≥ 3.13**.

**Install the common foundation, then choose an integration:**

```bash
uv sync
uv run rag init-db          # creates the DB + schema + roles, seeds the 'general' domain
uv run rag domain add programming --description "Software engineering notes"
uv run rag install          # Claude MCP/hooks + macOS backup schedule; omit for Codex-only
```

- `rag init-db` creates the database if needed, applies the migrations in `sql/`, creates the three least-privilege roles, and seeds the built-in `general` domain. **Run it first** — `rag install` does *not* create the database.
- `rag domain add <name>` adds any domains you want to organize documents under (`general` always exists; add more anytime).
- The no-option `rag install` is the Claude target: it registers the
  `agentic-rag` (read-write) and `agentic-rag-ro` (read-only) MCP servers and
  merges three hooks into `~/.claude/settings.json`. On macOS it also schedules
  nightly backup; omit this command for a Codex-only setup.

If you ran the Claude target, restart Claude Code so it picks up the new
servers and hooks. For humans the same store is available through the CLI:

```bash
rag save --title "Postgres VACUUM tuning" --domain programming \
    --dtype lesson --body "autovacuum_vacuum_scale_factor tradeoffs..."
rag search "vacuum tuning" --domain programming
rag get <slug-or-id>          # body + incoming/outgoing graph edges
rag status                    # counts, queue health, last backup/curation
```

For Codex continuity, preview before touching your user configuration, install,
then inspect and trust the changed commands in Codex:

```bash
uv run rag install --codex --check
uv run rag install --codex
# Start Codex, run /hooks, inspect all six agentic-rag commands, then trust them.
uv run rag status
```

The Codex transaction manages only `~/.codex/config.toml`,
`~/.codex/hooks.json`, and `~/.codex/compact_prompt.md`. It prints every
changed path, backup, validation result, and a ready-to-run rollback command:

```bash
uv run rag install --codex --restore /absolute/path/to/codex-rollback-<id>.json
```

Use the exact rollback-record pathname printed by the successful install.
Check mode writes nothing. The global rollout and end-to-end smoke tests are
still open in [`BACKLOG.md`](BACKLOG.md); repository support does not mean this
checkout has modified or verified a live user configuration.

The Codex target never installs a scheduler. On a Codex-only macOS setup, use
`uv run rag backup --install-launchd` for scheduled database backups; Linux
uses the handbook's cron/systemd recipes.

---

## What makes it different

Four things that, together, set it apart from both file-based knowledge wikis and hosted RAG stacks:

### 1. Real hybrid search over a curated graph
Documents are chunked and embedded into `halfvec(1024)` columns indexed with **HNSW**, and each chunk is embedded with the multilingual `bge-m3` model — so semantic recall works in any language — and also carries generated `tsvector`s for English/German keyword full-text. A single query runs vector ANN and full-text together and returns **one ranked list**. Documents aren't an undifferentiated pile: they carry a type (`concept`, `lesson`, `signal`, `synthesis`, `reference`, …) and connect through a **typed edge graph** (`references`, `extends`, `depends_on`, `supersedes`, `contradicts`, …), so `rag get` shows you not just a document but its neighbourhood.

### 2. Automatic session-mining — the star feature
This is what makes agentic-rag feel like it grows rather than sits there. When a supported coding session ends, a lifecycle hook enqueues the transcript. A **single-writer worker** drains the queue and calls the configured Codex or Claude CLI to pull out durable memories, lessons, and signals, each saved through the write gateway behind a **near-duplicate gate**. A fix you discovered today becomes something a future session can recall, with no "remember to write this down" step. It reads only your **local** session transcripts.

### 3. Knowledge domains you grow and curate
Domains are just data — a label for *where to look* (`general` is seeded at init). Add them with `rag domain add`, scope any search with `--domain`, and let the importer derive them from an existing store's topics. Curation is first-class: `rag review` reports near-duplicates, dangling links, and stale pins; refuting a fact archives it with a required reason + evidence; `rag purge` removes only already-refuted documents, and only as `rag_admin`.

### 4. Built-in maintenance, backup, and restore-testing
`rag backup` runs `pg_dump -Fc` locally (plus an optional copy to a synced directory you configure), with rotation. `rag maintenance` is a tiny, single-flight, always-exit-0 job that ticks the worker, rotates logs, and — **weekly** — runs a **report-only restore-test**: it restores your newest dump into an isolated scratch database, compares row counts, and drops it. A backup you've never restored isn't a backup; this one checks itself.

---

## How it works

```
   Supported coding sessions                rag save · migrate import · MCP write tools
   (queued & mined on session end)          (you, or an agent)
            │                                               │
            └───────────────────┬───────────────────────────┘
                                │
                    one audited write gateway
       strips secret-shaped tokens · chunks + embeds (local Ollama) · resolves edges · logs
                                │
                ┌───────────────┴────────────────┐
        PostgreSQL + pgvector              typed knowledge graph
        documents · chunks halfvec(1024)   edges: references · extends · …
        HNSW ANN  +  EN/DE full-text
                                │
                one hybrid ranked search  ──  vector ⊕ full-text
                                │
   session-start context · prompt-time recall · read-only MCP behind a privilege boundary
```

Codex continuity uses a separate operational path:

```text
PreCompact ──► bounded deterministic snapshot ──► audited checkpoint
     │                    └──► priority enrichment job ──► provider CLI
     ▼
Codex compacts
     │
PostCompact ──► mark boundary only (cannot inject context)
     │
SessionStart(source="compact") ──► bounded checkpoint context ──► next request
```

Native Codex memories are complementary, not the canonical record. With the
installed policy they remain enabled and can be inspected with `/memories`;
agentic-rag is canonical for durable searchable knowledge, audit history, and
explicit continuation checkpoints.

- **Your chosen CLI provider.** Every LLM call goes through the single `agentic_rag.llm` seam and the configured local Codex or Claude command. Embeddings never leave the box (local Ollama), so retrieval is independent of provider authentication.
- **One audited write path.** Every change — a manual `save`, a mined memory, an import — funnels through a single gateway that strips secret-shaped tokens, regenerates chunks + embeddings in one transaction, resolves dangling edges, and writes an audit row. Embeddings fail *open* (queued for retry if Ollama is down); nothing else does.
- **Least privilege, by role.** Three login roles enforce a destruction-protection matrix: `rag_reader` (SELECT only, used by search and the read-only MCP), `rag_writer` (INSERT/UPDATE but **no DELETE/TRUNCATE/DROP**), and `rag_admin` (migrate, purge, restore).
- **It steps aside, not in front.** If Ollama is down, search degrades to full-text-only and returns a warning rather than failing; the maintenance job always exits 0.

The full story is in the **[handbook](docs/README.md)** — the mental model, everyday use, configuration, importing an existing wiki, and the architecture and design rationale.

---

## Comparison

agentic-rag sits between two worlds: the file-based **LLM-Wiki** family (human-readable Markdown with a lint/graph layer) and typical **RAG stacks** (hosted or API-driven retrieval you feed documents to). Every cell below is marked honestly — including the rows where each of them beats us.

Legend: ✅ shipped in code and operationally established · 🧪 shipped in code, live rollout pending · ⚠️ partial / caveated · ❌ absent

### vs LLM-Wiki systems (file-based knowledge wikis)

| Capability | **agentic-rag** | File-based LLM-Wiki |
|---|:--:|:--:|
| Hybrid vector + full-text ranked search (ANN at scale) | ✅ | ⚠️ lexical/graph, file-scan |
| Bilingual full-text (EN + DE) + semantic recall | ✅ | ⚠️ |
| Transactional, audited writes through one gateway | ✅ | ⚠️ |
| Scales to a large corpus (HNSW index) | ✅ | ⚠️ file-scan slows |
| Human-readable, git-diffable plain-text store | ⚠️ import/export MD; store is Postgres | ✅ |
| Zero-infrastructure (no DB/service to run) | ❌ needs Postgres + Ollama | ✅ |
| Imports an existing llm-wiki store | ✅ `rag migrate` | ✅ it *is* one |

**Bottom line:** if you want a git-tracked pile of Markdown, a file-wiki wins on its home turf. If you want fast hybrid recall over a growing corpus with transactional safety, agentic-rag wins — and it can **import your existing llm-wiki** to get you there.

### vs typical RAG systems (retrieval frameworks / hosted memory)

| Capability | **agentic-rag** | Typical RAG stack |
|---|:--:|:--:|
| Local-first store, provider CLI under your control, no hosted RAG service ¹ | ✅ | ⚠️ usually a hosted service |
| Auto-populates from Claude Code sessions (mining) | ✅ | ❌ you feed it |
| Codex session mining and continuity | 🧪 | ❌ you feed it |
| Self-curation (dedup, near-dup gate, refute/archive) | ✅ | ⚠️ |
| Typed knowledge graph (edges) alongside vector search | ✅ | ⚠️ |
| One audited write gateway with secret stripping | ✅ | ❌ |
| Read/write privilege boundary for subagents (RO MCP) | ✅ | ⚠️ |
| Turnkey managed hosting / large ecosystem ² | ⚠️ self-host, young | ✅ |

**Bottom line:** a hosted RAG stack wins on turnkey scale and ecosystem. agentic-rag wins on being local-first, using a provider CLI under your control with no hosted RAG service in the loop, self-populating-from-your-own-work, and self-curating — a memory that fills and tidies itself instead of one you have to keep feeding.

<sub>
¹ agentic-rag is <strong>provider-configurable</strong>: LLM-assisted mining, curation,
and bounded checkpoint enrichment use the configured local CLI — Codex with a
ChatGPT login, or Claude with its supported OAuth or
<code>ANTHROPIC_API_KEY</code> authentication. Account limits and any metering
belong to that chosen provider. <strong>Embeddings are always local</strong>
(Ollama), so retrieval does not call a model provider, and there is no
third-party RAG service between you and your data. Most hosted RAG stacks route
your documents through a paid service.<br>
² agentic-rag is <strong>newly public</strong> and self-hosted — the field's clearest edge over us is turnkey managed hosting and a large plugin/integration ecosystem.
</sub>

---

## Configuration

Config lives in one TOML file at `~/.agentic-rag/config.toml`. Every key is optional — omit a section to keep its defaults.

| Setting | Default | What it does |
|---|---|---|
| `[db] name` | `agentic_rag` | Database name. |
| `[db] host` | `""` (local socket) | Empty = local unix socket; set it for a networked/remote server. |
| `[embed] model` | `bge-m3` | Ollama embedding model tag. |
| `[embed] dim` | `1024` | Fixed to the schema (`halfvec(1024)`); `init-db` refuses a mismatch. |
| `[ollama] url` | `http://localhost:11434` | Local Ollama endpoint. |
| `[backup] local_dir` | `~/.agentic-rag/backups` | Where `pg_dump` archives are written. |
| `[backup] cloud_dir` | — (unset) | **Opt-in** copy to a synced/cloud directory; unset = local-only, nothing leaves the machine. |
| `[pg] bin_dir` | auto-resolved | Only needed if `pg_dump`/`pg_restore`/`psql` aren't on `PATH` (e.g. Postgres.app). |

Roles are created **passwordless** by default, relying on local `peer`/`trust` auth (Postgres and agentic-rag on the same machine). For a networked or shared instance, set role passwords with `ALTER ROLE …` and let libpq authenticate via `~/.pgpass` or `PGHOST`/`PGPORT`/`PGPASSWORD` — see the handbook's privacy chapter.

The Codex target separately manages a 600000 context window and a 500000
total-token compaction threshold, leaving a 100K reserve, plus native memories
and the compact prompt. Official GPT-5.6 capacity is 1.05M, but inputs above
272K are subject to higher provider pricing and may add latency; see
[Configuration](docs/06-configuration-reference.md) and
[Privacy, cost & control](docs/07-privacy-and-cost.md).

---

## 📖 Documentation / Handbook

The full story lives in the **[agentic-rag Handbook](docs/README.md)** — a single, progressively-ordered read from the mental model through everyday use, configuration, importing, and the engine's architecture and design rationale. A few key chapters:

- **Understand** — [What is agentic-rag?](docs/01-what-is-agentic-rag.md) · [The mental model](docs/02-mental-model.md)
- **Use** — [Quick start](docs/03-quick-start.md) · [Working with your memory](docs/04-working-with-memory.md) · [Session mining & curation](docs/05-session-mining-and-curation.md)
- **Configure** — [Privacy, cost & control](docs/07-privacy-and-cost.md)
- **Develop** — [Architecture](docs/10-architecture.md) · [Reference — CLI & MCP](docs/11-reference-cli-and-mcp.md)

Start at the **[handbook index](docs/README.md)** for the one-line "what you'll learn" map of every chapter.

---

## Status

agentic-rag is **young but solid** — a real engine, openly developed. Repository
and rollout state are listed separately below:

- ✅ **Storage & search:** PostgreSQL + pgvector schema, HNSW ANN blended with EN/DE full-text into one ranked list, the typed edge graph, the three-role destruction-protection matrix.
- ✅ **The write gateway:** secret stripping (in and out), one-transaction chunk + embed + edge-resolve + audit, embeddings that fail open with a retry queue.
- ✅ **Session mining:** hooks → queue → single-writer worker → configured Codex/Claude CLI → gateway, with a near-duplicate gate and provider-outage circuit breaker.
- ✅ **Curation & safety:** `rag review`, refute-as-archive, and admin-only `rag purge` (removes only already-refuted documents, as `rag_admin`).
- ✅ **Maintenance & backups:** `pg_dump` backups with rotation, the tiny always-exit-0 maintenance job, and the **weekly report-only restore-test**. macOS auto-schedules via `launchd`; Linux uses the documented cron/systemd recipes.
- ✅ **Claude integration:** two user-scope MCP servers (read-write + a read-only server behind a privilege boundary for subagents), idempotent install that preserves foreign hooks.
- ✅ **Codex continuity in code:** audited checkpoints, bounded capture and
  restoration, asynchronous enrichment, all six lifecycle handlers, a
  versioned compact prompt, recoverable installer/check mode, and checkpoint
  health in `rag status`.
- ⬜ **Codex continuity live rollout:** the pre-install whole-diff/security
  review and live global install, `/hooks` trust, manual/automatic compaction,
  provider-recovery, and SessionEnd smoke tests remain open. See
  [`FEATURES.md`](FEATURES.md) and blocker-first [`BACKLOG.md`](BACKLOG.md).
- ✅ **Quality:** a content-free repository with a comprehensive local test
  suite; exact verification counts belong in rollout evidence, not a static
  badge.

The clearest gap relative to the field is maturity: it's newly public and self-hosted, without the turnkey hosting or large ecosystem of established RAG stacks.

---

## Acknowledgments

agentic-rag builds on other people's ideas and tools:

- **Andrej Karpathy** — the [LLM-Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) that shaped the durable-knowledge model this import path speaks to.
- **The llm-wiki format** — topic-partitioned Markdown with an optional memory store; `rag migrate` imports it wholesale, so an existing wiki carries straight over.
- **[pgvector](https://github.com/pgvector/pgvector)** and **[Ollama](https://ollama.com)** (`bge-m3`) — the local vector search and embeddings underneath everything.
- **Anthropic** — Claude Code, its hooks, and the MCP integration agentic-rag plugs into.

---

## Contributing

Tests come first (TDD), and `docs/` is kept in step with the code. A **warn-only doc-reminder hook** ships under `.githooks/`: if a commit touches `agentic_rag/` or `sql/` without touching `docs/`, it prints a reminder — it never blocks. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

Run the suite with `uv run pytest`. See the handbook's [Contributing](docs/12-contributing.md) chapter for dev setup, the test database, and code layout.

## License

[MIT](LICENSE). The repository is **code-only and content-free** — your documents, embeddings, and config stay in your own PostgreSQL database, on your own machine.
