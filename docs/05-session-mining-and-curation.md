# Session mining & curation

*What you'll learn: how a Claude Code session turns into stored knowledge with
no action from you — the Stop hook, the queue, the single-writer worker, the
`claude -p` extraction call, the near-duplicate gate — and how the store keeps
itself honest afterward: dedup, dangling-link and stale-pin review, and
refute/purge.*

This is the headline feature. Everything else in agentic-rag — the schema,
the search, the gateway — exists to make this loop possible: **you work, and
the memory fills itself.**

## The loop, end to end

1. You have a Claude Code session. Nothing you do is special — no
   `memory_save` calls required.
2. Each time Claude finishes responding, the **Stop** hook fires. It
   enqueues the session's transcript for mining and returns in well under
   100 ms — it never blocks your terminal. (A debounce in the queue, not in
   the hook, keeps this from triggering a `claude -p` call on every turn —
   see below.)
3. A detached background process, the **worker**, wakes up. If another
   worker is already running, this one exits immediately — there is always
   at most one.
4. The worker drains the queue: for each mining job, it builds a **digest**
   of the transcript (local file, redacted, only the new part since last
   time) and runs `claude -p` — through your local `claude` CLI, using
   whatever it's authenticated with (your Claude subscription or API key) — to
   extract durable memories, lessons, and error signals as schema-constrained
   JSON.
5. Each extracted item is checked against the store for a near-duplicate,
   then written through the write gateway (secret-stripped, chunked,
   embedded, audited).
6. The worker then runs a bounded **curation** pass: resolve dangling edges,
   merge exact duplicates, and review any mined contradictions against
   existing documents.
7. Later, in another session, **SessionStart** injects the pins and
   project-relevant documents that resulted, and **UserPromptSubmit** can
   recall a stored signal the instant you paste an error that matches one.

Nothing in this loop reaches outside your machine except the `claude -p`
call itself, which goes through your local `claude` CLI login — the same way
a normal Claude Code session talks to Claude. There is no separate telemetry
and no other transcript ever leaves your disk.

## Three hooks: two that feed the loop, one that closes it

### Stop — enqueue for mining

Fires after every assistant turn. It reads `transcript_path` and
`session_id` from the hook payload, inserts a `mine` job into the
`mining_queue` (if one isn't already pending or processing for this
session), and spawns the worker as a detached subprocess. Debounce lives in
the queue insert itself, not in the hook: at most one open `mine` job per
session at a time, and a fresh job only becomes due
`mine_debounce_seconds` (default 600s / 10 minutes) after it's created. Once
that job is queued, later Stop calls in the same session are no-ops until
the worker actually processes it — so a long session doesn't trigger a
`claude -p` call on every single turn. When the job does run, its digest
covers everything since the last mined turn; any further tail turns get
picked up by the next Stop, or by the next SessionStart that finds a due
job. Any error is logged and swallowed; the hook always exits 0 and prints
nothing.

### SessionStart — inject context, and check for overdue curation

At the start of an interactive session, this hook builds and injects: every
matching pin (uncapped, with a warning if the pin budget is exceeded), the
domain map, and the most recently touched documents scoped to your current
project. It also checks two things that spawn the worker without doing any
work itself: whether curation hasn't run in the last 24 hours (if so, it
enqueues a `curate` job), and whether any queued job is already due (the
tail of a previous session that the debounce window hadn't reached yet). On
*any* failure it still injects a visible `⚠️ agentic-rag unavailable: …`
message — silence about missing context is treated as a bug, not a
degrade-gracefully case.

### UserPromptSubmit — prompt_recall

A much narrower, much faster hook. It scans your prompt for a strong error
signature — a traceback, an `XError:`/`XException:` pattern, "No such file or
directory", a `path/file.ext:123` reference, a panic/segfault marker — and,
only if it finds one, runs a deterministic full-text query (no LLM, no
embedding call, well under 50 ms) against stored **signal** documents and
pins. A hit gets injected as advisory context: "stored knowledge matches
this error — verify before acting." It's deliberately conservative: plain
questions never trigger it, because precision matters more than recall for
something that runs on every prompt. This is also where mined `signal`
documents pay off later — a signature mined from one session's failure
becomes something a future session's identical error can recall.

## The queue and the single writer

Every mining, curation, retry-embed, and opportunistic-backup job lives in
one `mining_queue` table. The worker is a short-lived process, spawned
on-demand by hooks (never a daemon), that:

- Takes an exclusive `flock` on a lock file before doing anything. If the
  lock is held, it exits 0 immediately — it never queues extra work behind
  a busy sibling. Using `flock` instead of a PID file matters: the kernel
  releases the lock the instant the process dies, so a killed worker can
  never leave a stale lock behind.
- Requeues any job stuck in `processing` from a previous run — the flock
  guarantees only one *live* worker, so a `processing` row found at startup
  can only mean the last worker died mid-job (SIGKILL, OOM-jetsam). Without
  this, one orphaned job would silently disable curation forever.
- Drains up to 50 pending jobs, oldest-due first, each in its own
  transaction. A failed job is retried with exponential backoff
  (`worker_backoff_seconds`, default 300s, doubling per attempt) up to
  `worker_max_attempts` (default 3), after which it's marked `error` and
  surfaces in `rag status` and `rag review`.
- Runs a curation pass after draining, then an opportunistic backup if the
  newest local dump is more than 24 hours old.
- Logs everything to `~/.agentic-rag/log/worker.log` and **always exits 0**
  — a worker crash must never surface as a hook failure or block your
  session.

## What gets mined, and how

### The digest: local, redacted, delta-only

Before any LLM call, the transcript (a JSONL file on your own disk) is
reduced to a **digest**: user/assistant prose plus tool *names* — tool
inputs and tool-result bodies are deliberately excluded, because that's
where secrets and bulk noise live. The one exception is agentic-rag's own
memory tools (`memory_search`, `memory_get`, …), whose slug or query
argument is kept as a short hint so mining can reference documents you
already looked up by name. Prose is secret-stripped at digest time — before
the gateway's own stripping pass sees it at all. The digest also picks up
only what's new since the last successful mining job for that session (the
queue carries the last processed transcript position forward), and is capped
in size (`mine_max_digest_chars`, default 12000 chars, `mine_per_block_chars`
per message, default 800). Nothing about this step calls out to anything —
it's pure local file parsing.

### The `claude -p` call: your own Anthropic account, however you pay for it

The digest, the list of live domains, and any pins that scope to this
project go into one prompt, sent to `claude -p --model <llm_model>
--json-schema <schema>` (default model `haiku`, configurable). This runs
through your local `claude` CLI, using whatever that CLI is authenticated
with — your Claude subscription (OAuth login) or an `ANTHROPIC_API_KEY`. The
choice is yours; agentic-rag neither imposes nor refuses one. On a
subscription these calls add nothing beyond your plan; with an API key they
are metered by Anthropic like any other API use — your call. The child
process also has the Claude-Code session markers stripped from its
environment and an internal kill switch set, so a mining subprocess can't
recurse into the parent session or trigger its own Stop hook and re-mine
itself.

### Grounded or dropped

The `--json-schema` constrains the model's output shape: domains must be one
of the live domain names, edge predicates must be one of the fixed set
(`references`, `extends`, `depends_on`, `complements`, `contrasts_with`,
`informs`, `part_of`, `derived_from`, `supersedes`, `contradicts`,
`duplicate_of`). Anything the model returns that doesn't parse cleanly — a
missing title, an unrecognized domain, a signal-typed item with no literal
signal text — is **dropped in code, never repaired or guessed at**. An
unremarkable session that produced nothing worth keeping is expected to come
back with empty lists; that's treated as the correct answer, not a failure.

Per session, mining can produce (capped at 8 items per kind, 5 edges per
item):

| Kind | Saved as | Notes |
|---|---|---|
| `memories` | `memory` document | a durable fact worth keeping |
| `lessons` | `lesson` document | something learned the hard way |
| `signals` | `signal` document | a *literal* observable error string a future occurrence would contain — this is what `prompt_recall` matches against |
| `contradictions` | `lesson` document + `contradicts` edge | this session's evidence conflicts with an existing document (grounded only by a slug that literally appears in the digest) |
| `pin_suggestions` | audit-log row only | a standing rule the model saw you state — never auto-pinned |
| `contradictions_with_pins` | audit-log row only | evidence conflicting with a stored pin — pins are never touched automatically |
| `domain_proposals` | audit-log row only | content that fit no existing domain — never auto-created |

The last three are deliberately inert: nothing changes in the store beyond
one audit row. A human (or you, in a later session) reviews them via
`rag review` and decides.

## The near-duplicate gate

Before every mined memory/lesson/signal is saved, agentic-rag embeds
`title + body` and checks it against active documents in the same domain. If
cosine similarity to the closest existing document is at or above
`dedup_threshold` (default `0.90`), the new document is still saved — mining
never blocks on this — but it's saved with an extra `duplicate_of` edge back
to the near-duplicate, evidence-stamped with the similarity score, and
counted as a duplicate in the worker's log. That edge is exactly what later
shows up in `rag review`'s duplicate-candidate list for you to resolve. If
Ollama is unreachable at mining time, the gate is skipped entirely (best
effort, not a blocker) and the item is saved without a duplicate check.

## Curation: keeping the store honest

Curation runs automatically after every drain, and is also guaranteed at
least once every 24 hours (SessionStart enqueues a `curate` job if the last
one is stale). Each pass, bounded by a shared budget (`curation_budget`,
default 20 actions total):

- **Resolves dangling edges** — deterministic: any edge whose `dst_slug`
  now matches a document that didn't exist when the edge was created gets
  its `dst_id` filled in. No LLM involved.
- **Merges exact duplicates** — two *active* documents in the same domain
  with byte-identical bodies: the newer one is archived with a
  `duplicate_of` edge to the older. Safe because nothing about the content
  is lost — it's a literal copy.
- **Reviews mined contradictions** — one `claude -p` call per candidate. A
  candidate is any active document with an incoming `contradicts` edge from
  mining that hasn't been reviewed since that edge appeared — this is a
  deterministic worklist, not a fuzzy search. The review call sees the
  stored document and the contradicting session evidence, and can only
  answer `refute=true` with a reason and a literal quote, or `refute=false`
  ("when in doubt, refute=false"). Every candidate gets a `refute_review`
  audit row either way, which is also what keeps it from being reviewed
  again next pass.
- Writes one `curation_pass` audit row summarizing counts.

Pins are never touched by curation — only flagged as stale for a human to
re-verify.

## Refute is archive, not delete

A refuted document is not gone. Its `status` flips to `refuted`, and the
schema requires — enforced by a database constraint, not just application
code — a `refuted_reason` and `refuted_evidence` to go with it, plus a
`refute` audit row. The document stays in the database, out of active
search results, with a full record of *why* it was refuted and *what*
contradicted it. Nothing is hard-deleted until you explicitly run
`rag purge`.

## `rag review` and `rag purge`

`rag review` is the on-demand human worklist — everything curation flagged
but didn't (or couldn't) resolve on its own:

- duplicate candidates (`duplicate_of` edges between two still-active
  documents)
- dangling links (edges whose target slug still doesn't resolve)
- stale pins (unverified longer than `stale_days`, default 30)
- mining suggestions (`pin_suggestion`, `pin_contradiction`,
  `domain_proposal` audit rows — the inert items from mining, above)
- queue errors (jobs that hit `worker_max_attempts` and gave up)

`rag purge [--older-days N] --yes` hard-deletes documents that have been
`refuted` for more than `N` days (default 30). It refuses to run without
`--yes`. It runs on an **admin** database connection deliberately — the
`rag_writer` role the worker and hooks use cannot issue `DELETE` at all, by
grant, so purge is the one place in the whole system capable of permanent
deletion, and it is never called by automation. Every purge writes an audit
row naming which slugs were removed.

## Safety properties, in one place

- **Single writer.** Whatever else is running — a hook, a stale process, a
  parallel session — at most one worker ever touches the queue or runs
  curation. Contention means skip, never queue extra work.
- **Fail-open hooks, never a blocked session.** Every hook swallows its own
  errors and exits 0. A dead database, a missing `claude` binary, an
  unreachable Ollama — none of it can stop you from working; at worst you
  lose the context injection (and SessionStart tells you so, visibly).
- **Auth-agnostic, local-first.** Mining and curation run on your own
  Anthropic account through your local `claude` CLI — subscription or API
  key, your choice; agentic-rag never dictates which. There's no separate
  hosted service in the loop, and embeddings are always local (Ollama), so
  retrieval and embedding cost nothing either way.
- **Local transcripts only.** The only input to mining is a JSONL file
  already sitting on your disk. Tool-result bodies and tool inputs (other
  than a memory-tool slug/query hint) never enter the digest at all.
- **Audited.** Every save, merge, refute, purge, and even the inert
  suggestions carry an `audit_log` row with an actor (`mining` or `cli`) and
  a summary.
- **Archive, not delete.** The only path to permanent deletion is an
  explicit, confirmed `rag purge` on an admin connection, for documents that
  have already sat refuted for weeks.

## Next →

[06 · Configuration reference](06-configuration-reference.md) — every
`config.toml` setting behind the numbers in this chapter (debounce, dedup
threshold, curation budget, worker retries, and more), with defaults and
environment overrides.
