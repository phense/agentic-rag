---
id: C-065
title: Pattern synthesis
type: reference
doc_id: standalone
readers: [operators who enable it, agent users who read patterns]
status: draft
version: 0.6.18 (schema030)
depends_on: [claim-evidence.md, fact-validity.md]
assets: []
last_reviewed: 2026-10-31
summary: What a pattern suggestion is, how to switch synthesis on for one domain and project, how to read and check a pattern, and what happens when sources change or a run fails.
---

# Pattern synthesis

Reader: someone who already stores memories with source evidence and can read
it with `rag evidence show` ([claim evidence](claim-evidence.md)).

Several users sometimes report the same problem in separate sessions: names stop
resolving after a VPN reconnect, and restoring the DNS suffix fixes it. Each
memory alone is one observation. Pattern synthesis lets a model read a small,
bounded set of such memories and suggest the common pattern. The suggestion is
stored as an **inference**: a reviewable hypothesis with exact citations, never a
user statement and never a verified fact.

The feature is off by default. It runs only for a domain and project that an
operator switched on, and it never reads memories written before that moment
unless the operator asks for a bounded history window.

## What a pattern is

A pattern has a short label, one statement, the model's own confidence
(`low`, `medium`, `high`) and up to six parts. Each part cites the exact stored
quotes it rests on: the original memory, its evidence version (`ev1:…`), the
source reference and the source version (`src1:…`).

Three separate things describe a pattern, as for every claim:

| Field | Meaning | Who changes it |
|---|---|---|
| `confidence` | How sure the model said it was | The model, once |
| `review_state` | `unreviewed`, `confirmed` or `refuted` | An operator, with `rag evidence review` |
| `current` | Whether every cited source still says the same thing | Computed on every read |

An unreviewed pattern stays out of ordinary search, like every unreviewed
inference. You find it with `rag pattern list` and `rag pattern show`.

## How much support a pattern needs

A model is only asked when there are at least **three independent user events
across three different memories**. Two quotes count as the same event when they
come from the same source or are the same text after normalizing case and
whitespace, so an imported copy of one report does not count twice.

Only original memories qualify. Excluded, with the reason shown in the preview:

| Reason | What it means |
|---|---|
| `derived` | Another pattern or a `synthesis` document; patterns never feed patterns |
| `legacy_unmanaged` | An old memory without claim evidence |
| `not_stated` | An inference or proposal rather than something a user stated |
| `no_qualifying_span` | No complete user quote from an active, non-manual source |
| `not_current` | Refuted, withdrawn, expired or otherwise not current |

Each model call sees at most 12 memories with at most 8 quotes each, and the
whole input, instructions included, must fit `max_input_chars` (default 12,000
characters). Every suggestion may cite at most 8 quotes.

## Switch it on

Two switches are needed. The global one is in the configuration of the process
that runs the worker (on a central service: the server):

```toml
[synthesis]
enabled = true
```

All keys are in the [configuration reference](06-configuration-reference.md#synthesis).
Then an operator switches on one concrete domain and project. Look first:

```sh
rag pattern preview --domain general --project /work/helpdesk
```

The preview calls no model and writes nothing. It shows how many memories qualify,
how many independent events they contain and whether that reaches the floor of 3.
If it does, enable the scope:

```sh
rag pattern enable --domain general --project /work/helpdesk --reason "helpdesk trial"
```

Before the first enable, every process that opens the database directly must
run 0.6.18 and have been restarted since the upgrade; the check is step B0 of
[PB-065-OPS](playbooks/system/rag-065-pattern-synthesis.md).

The answer names the policy version and the **forward boundary**, the server time
of enabling. From then on, the existing worker considers new memories in that
scope on its normal tick, at most once per interval (default one day,
`--interval-seconds`). Use `--scope global` instead of `--project` for global
memories.

### Which memories a run reads

A run reads two kinds of memories:

- **New** memories: created after the forward boundary and not yet read by a
  finished run. A memory counts as read only when its run ends `applied` or
  `non_conclusion`. A save that takes long and commits after a later memory was
  already read is still picked up on a later tick.
- **Context**: up to the remaining room, recently read memories of the same
  scope, those not yet cited by a current pattern first. This is how three
  reports that arrive on different days still end up in one call. Context alone
  never starts a run.

New memories are taken in arrival order until the next one would not fit the
input limit or 12 memories. The rest waits for the next run, which is due at
once. `rag pattern status` shows the policy line with `pending N` (new memories
not yet read) and, when something blocks, one of these notes:

| Note | Meaning | What to do |
|---|---|---|
| `(insufficient_independent_support)` | Not yet 3 independent events | Wait for more memories |
| `(input_budget_below_floor)` | 3 independent events exist, but they do not fit the input limit together | Raise `max_input_chars` (at most 24,000) and restart the worker |
| `oversized N` | A memory does not fit the input limit even alone | The same; a memory over 24,000 characters cannot be read |
| `held for recovery N` | Memories of a run waiting for `rag pattern recover` | See *Results of a run* |

Nothing is sent to the model and nothing is marked as read while a note blocks.
The context window is finite (the 48 most recently read memories of the current
enable period): two reports far apart in a long history are not guaranteed to
meet in one call.

## Older memories: backfill

Memories created before the forward boundary are never read automatically, not
even after disabling and enabling again. To include them, request a bounded
window:

```sh
rag pattern backfill --domain general --project /work/helpdesk \
  --start 2026-09-01T00:00:00Z --end 2026-10-01T00:00:00Z --reason "September reports" --max-batches 2
```

The window ends at or before the forward boundary, spans at most 366 days and
runs at most 10 batches. Below the support floor a backfill ends without a model
call.

## Read and check a pattern

```sh
rag pattern status --domain general --project /work/helpdesk
rag pattern list --domain general --project /work/helpdesk
rag pattern show vpn-reconnect-clears-the-dns-suffix-list
```

`show` prints the label, statement, confidence, review state, the support count
and every citation. To read a cited quote, take the part of the reference before
`#` as source key:

```sh
rag evidence show vpn-reconnect-name-resolution-a --source <source_key>
```

Agents use the same operations through MCP: `memory_pattern_preview`,
`memory_pattern_status`, `memory_patterns` and `memory_pattern` on both servers;
`memory_pattern_policy`, `memory_pattern_backfill` and `memory_pattern_recover`
only on the read-write server ([reference](11-reference-cli-and-mcp.md#pattern-tools)).

To accept or reject a pattern, review it like any other claim:

```sh
rag evidence review vpn-reconnect-clears-the-dns-suffix-list --state confirmed --reason "checked with two users"
```

## When sources change

A pattern is only shown while everything it rests on is unchanged. It disappears
from every read, including `memory_get`, evidence, graph and pattern tools, when:

- a cited memory is refuted, withdrawn, expires or changes its evidence;
- a cited source is removed or its trust changes;
- the scope's policy is disabled;
- the reader may not see one of the cited memories.

Nothing is deleted. A withheld pattern reports `evidence_unavailable`, the same
answer as for a missing one. Undoing a source change does not bring it back: a
source that was withdrawn and then reinstated has a new version, so the pattern
stays withheld. Only enabling a disabled policy again shows its unchanged
patterns again. A backfill over the affected period can produce a fresh pattern
from the current versions.

## Results of a run

`rag pattern status` lists each run with its state and a code:

| State | Code | What happened |
|---|---|---|
| `applied` | | A pattern was written |
| `non_conclusion` | `insufficient_independent_support` | Below the floor; no model call |
| `non_conclusion` | `conflicting_sources`, `insufficient_evidence`, `ambiguous` | The model declined to conclude |
| `non_conclusion` | `conflicting_support`, `unknown_citation`, `too_many_citations` | The model's suggestion failed validation |
| `non_conclusion` | `invalid_output` | The answer did not fit the output schema; no retry. Its memories count as read and return only as context |
| `withheld` | `input_budget_exceeded` | `max_input_chars` was lowered after the run was planned; no model call, nothing marked as read |
| `withheld` | `policy_changed`, `source_changed`, `authorization_changed` | Something changed before the result was recorded; nothing marked as read |
| `error` | `job_failed` | The worker gave up before the model answered; its memories are read again later |
| `error` | `apply_failed` (`recoverable`) | The answer was accepted but could not be written; its memories are held for recovery |

When the model provider is unreachable, the run stays `pending` and the worker
tries again after its normal provider backoff. A run marked `recoverable` kept
its accepted answer. Re-queue it without a new model call:

```sh
rag pattern recover <run_id> --reason "database was full"
```

## Switch it off

```sh
rag pattern disable --domain general --project /work/helpdesk --reason "trial ended"
```

Existing patterns are withheld at once, never deleted, and no new run starts.
Setting `[synthesis] enabled = false` stops all scheduling, model calls and new
backfills in every scope; existing patterns stay readable while their policy is
enabled.

Returning to 0.6.17 depends on whether a pattern exists. Without any pattern,
only the code goes back. Once a pattern exists, running 0.6.17 against the store
is not supported, even with every policy disabled: its `memory_get`, evidence
and graph lookups by id would show disabled or stale patterns. The way back is
then the verified backup taken before the upgrade, which loses every later
write. The operator steps are in
[PB-065-OPS](playbooks/system/rag-065-pattern-synthesis.md), part D.

## Limits

- The validator checks citations, the support floor and declared stances. It
  cannot tell when a model calls a contradicting quote "supporting". The frozen
  measurement shows one such case
  ([measurement](benchmarks/2026-10-31-pattern-synthesis/README.md)). Treat every
  pattern as a hypothesis until reviewed.
- Measured only with scripted model answers on a synthetic corpus; no real-model
  quality figure exists yet.
- 0.6.17 code with direct database access must not run once a pattern exists
  (see *Switch it off*). The B0 check covers the hosts you list and the clients
  connected at that moment; it cannot discover a host you did not name.
- Recurrence is found within one run's memories: new ones plus the finite
  recent context. Comparison of every pair in a large history is not promised.
- A memory larger than the maximum input limit is reported as `oversized` and is
  never analysed.

## Terms

| Term | Meaning |
|---|---|
| Pattern | A stored inference over several original memories, with exact citations |
| Policy | The switch for one domain and project (or global scope) |
| Forward boundary | The server time of enabling; earlier memories need a backfill |
| Independent event | A distinct user report, after merging same-source and same-text quotes |
| Run | One scheduled attempt: selection, at most one model call, validation, writing |
| Non-conclusion | A run that ended without a pattern, with a reason |
| Withheld | Hidden from reads because something it rests on changed; not deleted |
