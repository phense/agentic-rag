# PB-5.6: Research a compound question with bounded evidence

## Identity and scope

- Class: system operation, with code upgrade and rollback checks.
- Origin: [Issue31](https://github.com/phense/agentic-rag/issues/31), [RAG-5.6 requirements](specs/RAG-5.6-bounded-research/spec.md).
- Audience and owner: CLI/MCP operators; repository maintainer owns rollout approval.
- Target: Feature6 code on the existing source `19ed09c1b3c46d907254f63a1370586ea3213966`, schema001–016, one shared PostgreSQL store.
- Readiness deadline: before code adoption or operational use.
- Last edited: 2026-10-03.
- Review and rehearsal evidence: [verification record](verification/bounded-research.md); practical results [here](benchmarks/2026-10-03-bounded-research/README.md).

## When to use / when not to use

Use `rag research` or `memory_research` when a question needs several searches,
related source passages, or an explicit account of conflicting and missing
evidence. Ordinary `rag search` remains the shorter route for a single lookup.
Research reads existing knowledge; it does not save answers, change evidence
review, or decide trading actions.

The result separates `supported`, `disagreement`, and `missing_evidence`.
Each supported statement is a literal source excerpt with at least two distinct
upstream source keys by default. Chunks from the same source do not create a
quorum. Only confirmed stated claims with reviewed, complete, active user
sources qualify. Legacy, unreviewed, assistant, proposal and refuted evidence
may be shown but cannot become supported statements.

Local mode always sets `abstained=true`: exact quotations can be checked locally,
but whether they answer the whole question requires interpretation. Explicit
provider mode adds that assessment. Its output still has to quote retained
source text exactly and meet the source quorum; it cannot create new citations.
A model assessment is fallible, and distinct source IDs do not establish
independent human authorship. Inspect the cited passages before relying on them.

## Before starting

1. Run `rag research --help` with the intended installed executable. Expect the
   budget and filter options below; if absent, use the old `rag search` until
   an approved code deployment completes.
2. Select the intended domain and project or explicit scope. Research carries
   them through every search and both graph endpoints. Use `--as-of` with an
   ISO-8601 timezone for a historical instant, or `--history` for historical
   eligibility; the two options are mutually exclusive.
3. Decide whether this request may send a redacted question and selected stored
   excerpts to the configured Codex or Claude account. Keep `--provider` absent
   for local processing. Secret stripping reduces exposure; it does not make
   private content public or authorize a new provider transfer.

| Input | Default | Accepted bounds |
|---|---:|---|
| `--steps` | 4 | 1–8 collect/check rounds |
| `--calls` | 16 | 1–40 logical search, graph and provider operations |
| `--seconds` | 30 | finite 0.1–180 seconds |
| `--context-chars` | 12000 | 512–32000 serialized evidence characters |
| `--min-sources` | 2 | 2–8 distinct qualified source keys per statement |
| `--strategy` | auto | auto or lexical; lexical skips query embedding |

Calls count logical operations, not every nested SQL statement or HTTP request.
The parent deadline includes worker startup, scope resolution, retrieval and
provider work. Process termination/reaping adds OS cleanup time. The context
cap covers the serialized evidence packet, not the full result or provider
instructions; extra records are omitted whole, with a warning.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| R1 | Operator, selected store | Run local research with explicit filters. | Original citations and separated result categories. | Invalid input: correct flags; incomplete result: R3. |
| R2 | Operator, configured provider | With request-specific transfer authorization, add `--provider`. | Usage includes provider calls; exact quoted claims retain source quorum. | Planning/check failure falls back to local abstention; do not infer completion. |
| R3 | Operator, result | Inspect `termination`, `abstained`, missing facets, disagreements and warnings. | Complete answer assessment requires provider success and coverage of all facets without unresolved conflicts. | Follow cited sources or narrow the question; R4 for interruption. |
| R4 | Operator, interrupted call | Cancel or allow the deadline to expire. | Worker descendants are reaped; deadline returns available partial evidence with abstention. | Preserve aggregate diagnostics; retry independently after correcting the cause. |
| R5 | Maintainer, candidate code | After specific merge approval and separate rollout authorization, adopt the reviewed code in the existing environment. | Source/candidate/rollback contracts and preserved state match verification. | Stop if schema differs from016 or runtime provider flags are unsupported. |

For R1, a normal command is:

```sh
rag research 'What is the storage decision? What constraints apply?' \
  --project /path/to/project --domain programming --json
```

Read `usage.search_calls`, `usage.graph_calls`, `usage.provider_calls`,
`usage.steps`, and `termination`. A successful process exit only means that a
result packet was returned; `abstained=true` is a valid, conservative outcome.
`complete` in local mode means local collection/checking stopped normally,
not that a semantic answer was proven.

For an isolated candidate checkout, use the canonical environment without
reinstalling its editable package:

1. Change the working directory to `/path/to/candidate` using
   `cd /path/to/candidate`. This matters because `python -m` searches its
   current directory before PYTHONPATH; running from the old canonical root
   would load old code.
2. Run the following command from that candidate root.
3. Inspect the result's budgets and termination, then follow R3/R4 if incomplete.

```sh
PYTHONPATH=/path/to/candidate /path/to/canonical/.venv/bin/python \
  -m agentic_rag.cli research 'What evidence is available?' \
  --project /path/to/project --strategy lexical --seconds 5 --json
```

MCP exposes the same read operation on both `agentic-rag` and `agentic-rag-ro`:
`memory_research(question, domain=None, project=None, scope=None, as_of=None,
history=False, provider=False, strategy="auto", steps=4, calls=16,
seconds=30.0, context_chars=12000, min_sources=2)`. Both privilege levels use
a fresh reader transaction with repeatable-read, read-only isolation. They
retain their existing six-tool write privilege difference.

## Interruption, recovery and rollback

Every request is independent. Two consecutive operation failures, the call
or step cap, or the parent deadline stop collection with explicit missing
evidence and abstention. Cancellation propagates to the caller after process
cleanup. The parent owns a private temporary directory and kills/reaps the
worker process group, including nested CLI processes. Existing PostgreSQL,
Ollama or remote provider services are outside that group; already-dispatched
work may finish on those services after caller cancellation.

Retries do not replay application writes because research has none. Do not
restore a database to recover a failed research request. Failed provider
planning/checking latches local mode for that request; a later round cannot
silently upgrade it to provider completion.

The supported upgrade is **code only** from `19ed09c` with schema016. There is
no new dependency, migration, backfill, configuration, hook or job change.
Existing users, domains, pins, checkpoints, audit history and queued work stay
in the same store. Old clients retain their old tool list until reconnect;
ordinary search contracts continue to work across old/new clients. Reconnect
an MCP client to expose `memory_research`; no database maintenance window is
required. No service interruption was used for the candidate verification.

For an authorized rollout, record the deployed code revision, existing schema
list, reader/writer tool lists and a verified existing backup before adoption.
Keep the previous code available. If post-adoption checks fail, restore the
previous code and reconnect affected clients; leave schema016 and data intact.
The isolated rehearsal exercises actual source, candidate and old-code rollback
CLI/MCP calls on one populated installation, plus a strict backup restore into
a separate empty database. It does not authorize live deployment or restore.

## Escalation and preserved evidence

Escalate unsupported provider CLI flags, repeated failures or unexpected
filter leakage to the maintainer through the existing Issue/PR workflow.
Capture revision, budget, termination, call counts and error classes. Keep
questions, private source snippets, credentials and provider output out of
public reports. Unsupported safety flags fail closed; do not remove them to
make an older CLI run.

## Completion

The operation is complete when a bounded result or propagated cancellation
has been observed, citations have been inspected for the intended scope, and
owned worker/temp resources have been cleaned up. A missing or disputed fact
remains unresolved. Code readiness, reviewed procedure, rehearsed recovery,
merge approval and live adoption are distinct states.

## Maintenance and sources

Revalidate after changes to CLI safety flags, source qualification, temporal
selection, graph queries, process cleanup, or schema contracts. Definitions:
[implementation](../agentic_rag/research.py), [worker](../agentic_rag/research_worker.py),
[CLI/MCP reference](11-reference-cli-and-mcp.md), [privacy](07-privacy-and-cost.md),
[as-built boundary](uml/bounded-research.md).
