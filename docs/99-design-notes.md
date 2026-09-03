# Design notes & rationale

*What you'll learn: the reasoning behind five decisions that shape everything
else in this handbook — the database instead of files, the single writer,
derived domains instead of a taxonomy, archive-not-delete, and
auth-agnostic LLM access — including where each one costs something. This
chapter doesn't hide the tradeoffs; it names them.*

Every other chapter describes *what* agentic-rag does. This one is about
*why*, and about what got given up to get there. None of these decisions were
free — the honest version of each includes the bill.

## Why Postgres + pgvector, not a file wiki

The obvious lighter-weight alternative to a database is what agentic-rag's
predecessor (and the sibling `ultra-memory` project) actually used: a folder
of topic-partitioned Markdown files, human-readable and git-diffable, with no
infrastructure to run. That approach has real advantages agentic-rag simply
does not have: you can `grep` it, diff it, edit it in any text editor, and
version it with tools every developer already owns. Zero services, zero
schema, zero moving parts.

agentic-rag trades that away for three things a plain file store can't give
you at scale:

- **Search quality.** Hybrid ranking — vector similarity fused with full-text
  ranking via Reciprocal Rank Fusion (see [02 · The mental
  model](02-mental-model.md)) — needs an ANN index (HNSW) and a query
  planner. A file-scan can grep for exact words; it can't rank a paraphrase
  against a keyword match in one pass.
- **Scale.** An HNSW index stays fast as the corpus grows into the thousands
  of documents; a directory of files degrades linearly with a full-text
  file-scan, and semantic search over files usually means loading embeddings
  into memory yourself.
- **Transactional integrity.** A write — secret-stripping, chunking,
  embedding, edge resolution, and the audit row — either all lands or none of
  it does, in one commit (see the gateway in [02 · The mental
  model](02-mental-model.md)). A set of files being written by more than one
  process at once has no equivalent guarantee.

The cost is stated plainly: you now need PostgreSQL and pgvector running
somewhere, and the knowledge itself lives in database rows, not files you can
open in a plain editor. That's real infrastructure in exchange for search
quality and safety a file store doesn't offer. agentic-rag doesn't pretend
this is free — it keeps a bridge back to the file-wiki world instead: the
`migrate` importer (see [08 · Knowledge domains &
import](08-knowledge-domains-and-import.md)) reads an existing llm-wiki store
and brings it in through the same gateway everything else uses. If a
git-tracked pile of Markdown is genuinely what you want, that's a fine
choice, and it isn't this project.

## Why a single writer

Every write in the system — session mining, curation, migration — funnels
through exactly one short-lived worker process, gated by a `flock` (not a PID
file) on `~/.agentic-rag/state/worker.lock`. However many Claude Code
sessions are open at once, at most one writer runs.

This exists because of a concrete failure mode in the predecessor system, not
a theoretical one. That system loaded a full embedding model inside *every
Claude Code session's own process*. A handful of sessions running at once
was enough to jetsam-kill a 16 GB Mac — more than once — before this project
was rebuilt around a different rule: hooks may only enqueue work and spawn
the singleton worker (a no-op if one is already running); they never do
write work in-process. However many sessions start concurrently, the "several
heavy processes at once" failure class is no longer physically possible,
because there's structurally nowhere for a second heavy process to run.

`flock` over a PID file specifically because the kernel releases the lock the
moment the holding process dies — a worker killed mid-job (by the OS, by a
crash) can never leave a stale lock behind the way a PID file can. The
flip side is handled explicitly: any `mining_queue` row still marked
`processing` when a new worker starts must belong to a worker that died
mid-job, so it's requeued rather than left to block the queue forever.

The single writer also closes a second problem for free: write races. Two
hooks firing near-simultaneously from two different sessions can't both try
to replace the same document's chunks at once, because there's only ever one
process doing that work, one job at a time, serially.

The tradeoff is throughput, and it's deliberate: mining and curation queue up
and drain one job at a time rather than running in parallel. For the scale
this is built for — one person's own Claude Code sessions — that's a good
trade. It would not be if agentic-rag were a multi-tenant service processing
many users' queues at once; it isn't trying to be that.

## Why domains are derived, not a taxonomy

A domain is a row in a `domains` table — a name and a description, nothing
more (`sql/001_init.sql`). There is no enum of allowed domains anywhere in
the code. A fresh install seeds exactly one, `general`, so `rag save` works
before you've organized anything; everything past that is `rag domain add`,
one command, one row.

The reasoning: any taxonomy baked into the tool would only ever fit the
author's own corpus. Knowledge domains are genuinely different from project to
project — there's no universal list of categories that fits everyone's use of
a memory store, and shipping one would mean every new user either contorts
their own knowledge to fit somebody else's categories or immediately deletes
the defaults and starts over. Treating domains as data sidesteps that
entirely: the importer that brings in an existing llm-wiki store derives
domains straight from the source's own structure — each top-level
topic-partition directory becomes a domain (slugified, falling back to
`general` for anything at the root) — so the taxonomy that comes out is
whatever taxonomy you already had, not one invented for you.

Candidly: this wasn't the design from day one. Earlier in this project's
life, the importer contained a hardcoded topic-to-domain map tuned to the
author's own corpus — it worked, but only for that one corpus. Generalizing
it to derive domains from the source's own directory structure was part of
making this importable by anyone with an llm-wiki store, not just its
original author. "Domains as data" was always the principle; the importer
just hadn't fully lived up to it yet.

## Why archive, never delete

Nothing in the normal path can hard-delete a document, and that's enforced at
two layers, not one.

**The schema layer:** a document's `status` can be `active`, `archived`, or
`refuted` — never gone. Setting `status = 'refuted'` without a reason is not
possible; a `CHECK` constraint (`refuted_requires_justification` in
`sql/001_init.sql`) rejects the update unless `refuted_reason`,
`refuted_evidence`, and `refuted_at` are all present. This is a database
constraint, not an application convention — code that "forgets" to pass a
reason fails at the database, not silently.

**The role layer:** the login role every normal write uses, `rag_writer`, has
no `DELETE`, `TRUNCATE`, or `DROP` grant on any table, anywhere
(`sql/002_roles.sql`; see [07 · Privacy, cost &
control](07-privacy-and-cost.md) for the full matrix). The one narrow
exception — replacing a document's chunks when it's re-embedded — goes
through a `SECURITY DEFINER` function scoped to a single `document_id`, not a
grant that could reach any other row. A bug that tries to run `DELETE FROM
documents` under the role every session and hook actually uses fails at the
database level, before it can do damage.

The reasoning underneath both layers is the same: archiving keeps the trail
("we used to believe X, here's why we don't anymore"); deleting erases it.
For an automated system whose whole purpose is remembering things
correctly, losing the record of a correction is worse than keeping a document
you no longer trust. Two-stage deletion follows from that: `archived` and
`refuted` documents drop out of search immediately but stay recoverable;
`rag purge` — the only thing that actually removes rows — only touches
documents refuted more than a configurable number of days ago, requires
`--yes`, and runs under `rag_admin`, the one role with the privilege to do
it.

Said plainly, the honest caveat: this is a guardrail against bugs and
careless code paths, not against a compromised or malicious admin. `rag_admin`
has full privileges by design, because `migrate`, `purge`, and `restore`
need them. The protection is real for the failure mode it targets — an
ordinary write accidentally deleting something — and it isn't a claim to
anything stronger than that.

## Why the LLM provider is one configurable seam

Every LLM call in the system — mining extraction, curation review, and bounded
checkpoint enrichment — goes through `agentic_rag/llm.py`. That chokepoint has
explicit Codex and Claude CLI adapters. Public defaults remain Claude/Haiku
for compatibility; a local deployment can select Codex/Luna/high and use the
CLI's ChatGPT login without adding a direct API client or key to agentic-rag.

The seam centralizes structured-output validation, timeouts, prompt handling,
and failure classification. A bad model response is a job failure; a missing
binary, timeout, or expired provider login is a provider outage. The latter
returns the job to `pending` without consuming its retry budget, stops the
current drain, and writes an atomic health artifact. This prevents one shared
authentication problem from exhausting every independent queue item.

Codex runs ephemerally in an empty temporary directory with repository and
user rules ignored and read-only sandboxing. Claude remains a configuration
rollback path. In either case embeddings are local (Ollama/bge-m3). The
configured provider receives mining inputs (a bounded secret-stripped digest,
live domain names, and secret-stripped copies of all matching pin bodies),
selected curation content for one document/evidence set, or a bounded
secret-stripped checkpoint delta.

## What this leaves open

None of the above is free, and it's worth saying so in one place:

- You need PostgreSQL and Ollama running before any of this works — that's
  two services a plain file-based approach doesn't ask for.
- The taxonomy-free domain model means a brand-new install starts with
  exactly one domain (`general`) and no opinions about how you should
  organize anything — useful for flexibility, less useful if you wanted
  guidance out of the box.
- Archive-not-delete means a store that's never curated accumulates archived
  and refuted rows forever until someone runs `rag purge` — the safety
  net is also, left unattended, a slow accumulation of dead weight.
- Provider-configurable LLM access means mining, curation, and checkpoint
  enrichment depend on the account and limits of the selected CLI, while
  embeddings stay local; the RAG leaves that tradeoff in your hands rather
  than deciding it for you.

Each of these is a considered choice for what this project is — a
local-first, single-user, RAM-lean memory layer — not an oversight. They're
also exactly the places a different set of constraints would justify a
different answer.

## Next →

[Handbook index](README.md) — back to the full chapter list.
