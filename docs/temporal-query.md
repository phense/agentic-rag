---
id: C-064
title: Temporal search
type: reference
doc_id: standalone
readers: [operators and agent users of rag search and memory_search]
status: drafted
version: 0.6.17 (schema029)
depends_on: [fact-validity.md, claim-evidence.md]
assets: []
last_reviewed: unreviewed
summary: How rag search and memory_search interpret yesterday, last week, next month and explicit dates, which event time they use, and how to enable, check and roll back the feature.
---

# Temporal search

Reader: someone who already runs `rag search` or calls `memory_search` and knows
the existing `as_of`/`history` options from [fact validity](fact-validity.md).

A question such as "backup job failed yesterday" contains a period. Without
temporal search, the words *yesterday* and *gestern* are ordinary search terms:
full-text search then requires them in the document, and the date of the event
plays no role. With temporal search, agentic-rag recognizes the period, removes
it from the search text when enough other words remain, and orders hits whose
recorded event time falls in that period first. It never invents a date and never
widens what you are allowed to see.

## Request options

Three optional arguments exist on `rag search`, `memory_search` (local and remote
MCP) and `POST /v1/tools/memory_search`. Calls without them behave exactly as in
0.6.16.

| Argument | CLI flag | Values | Meaning |
|---|---|---|---|
| `temporal` | `--temporal` | `auto` (default), `off`, `prefer`, `filter` | `auto` follows the `[temporal] enabled` setting of the process that runs the search (on a central service, the server). `prefer` orders matching hits first and keeps the others behind them. `filter` returns only hits with a known event time inside the period. `off` skips interpretation entirely. |
| `reference` | `--reference` | ISO-8601 timestamp with an offset, for example `2026-10-30T10:00:00+01:00` | The "now" that *yesterday*, *last week* and *next month* are counted from. Without it, the clock is read once per search. It changes interpretation only, never `as_of` or `history`. |
| `timezone` | `--timezone` | IANA name such as `Europe/Berlin` or `UTC` | Where calendar days start. Default: `[temporal] timezone`, otherwise `UTC`. |

`auto` with the feature disabled never changes a result. Explicit `prefer` and
`filter` work even when the setting is disabled, because the caller asked for them.
`auto` never filters; only an explicit `filter` can remove hits.

## Supported expressions

Intervals are half-open (`[start, end)`), computed from local midnights in the
chosen zone and reported in UTC. Days with a daylight-saving change therefore
have 23 or 25 hours.

| Expression | Interval |
|---|---|
| `yesterday`, `gestern` | The previous local calendar day |
| `last week`, `letzte Woche` (also `letzten`/`letzter`) | Monday 00:00 to Monday 00:00 of the previous calendar week |
| `next month`, `nächsten Monat` (also `naechsten`) | The complete next calendar month |
| `2026-10-14`, `14.10.2026`, `14. Oktober 2026`, `October 14, 2026` | That local day |
| `from 2026-10-01 to 2026-10-03`, `vom 01.10.2026 bis 03.10.2026`, `zwischen … und …` | Both days included |
| `currently`, `aktuell` | No interval. The existing current-validity selection applies; no recency window is invented. |

These are reported and never guessed: slash dates (`03/04/2026`), dates without a
year (`14.10.`, `5. Mai`), two-digit years, impossible dates (`2027-02-29`),
reversed ranges, timestamps with a time of day, unsupported periods (`today`,
`last month`, `vor 3 Tagen`, `recently`), two different periods in one query, and
a period combined with `currently`. A date inside another token, such as the slug
`release-notes-2026-10-14`, is not an expression. Queries longer than 1,000
characters are not interpreted.

When the query consists only of the period ("gestern"), or when removing it would
change an exact error symbol, the original text is searched unchanged.

## Which event time counts

The temporal stage looks only at hits that the normal search already returned
under your domain, project scope, access rights, trust and validity rules.

1. A document with an atomic assertion uses the assertion's event time and nothing
   else.
2. Otherwise it uses the times of its *qualifying* active sources: a source
   reviewed by an operator for a confirmed claim, or a complete user statement for
   a stated claim. A document matches when at least one of these times is inside
   the period.
3. Everything else is `unknown`. Document creation, update or import time is never
   used, so a note imported today about last week's outage matches *last week*.

An assistant repetition or a partial quote dated yesterday does not make a claim
match *yesterday*, even if another source makes the claim eligible. A known source
date says when something was stated; it does not verify the statement.

Refuted, withdrawn, expired, superseded, private or future assertions stay
excluded exactly as before. A future period alone does not make a future assertion
current. A stored future plan, for example a claim whose user source is dated next
month, can match *next month* because it was already eligible.

## What the response shows

The legacy envelope `{results, warnings}` is unchanged unless temporal
interpretation was requested or applied. Then two additions appear.

Top-level `temporal`:

| Field | Content |
|---|---|
| `requested`, `mode` | What the caller asked for and what ran (`prefer` or `filter`) |
| `status` | `interval`, `current`, `ambiguous`, `unsupported` or `none` |
| `interval` | `start`, `end` (UTC) and `bounds: "[start, end)"`, or `null` |
| `timezone`, `reference`, `reference_source` | The values used; `reference_source` is `request` or `clock` |
| `expressions`, `kinds`, `reasons` | The recognized text and why nothing was applied, for example `multiple_periods` or `metadata_unavailable` |
| `confidence` | `syntactic` when the grammar recognized the expression; it says nothing about factual truth |
| `retrieval_query` | `without_time_expressions` or `original` |
| `applied` | `preference`, `filter` or `none` |
| `effect` | Candidate documents examined, `matching`, `outside`, `unknown`, `excluded`, `reordered`, `graph_checked` |
| `limits` | `candidate_limit: 150`, `graph_node_limit: 20`, `recall: candidate_limited` |

Per hit, `evidence.temporal` holds `basis` (`assertion_event`, `source_event` or
`unknown`), `match` (`inside`, `outside` or `unknown`), `event_at` (UTC),
`qualifying_events` and `support` (`operator_review`, `user_source_event`,
`manual_attestation`). Source identifiers, namespaces and quotes are not included;
use [`rag evidence show`](claim-evidence.md) for those.

Scores, snippets and citations are the original values for the text that was
searched. With `prefer`, ties keep their original order. With `graph_depth`, the
same rule is applied again after graph expansion, so a linked document from
another period cannot jump ahead of matching hits or slip through a filter.

## Failure behavior

| Situation | `prefer` / enabled `auto` | `filter` |
|---|---|---|
| Ambiguous, unsupported or missing period | Original order, warning `temporal expression not applied: …` | Error `temporal_filter_requires_interval` (CLI exit 1, REST 400 `invalid_arguments`) |
| Invalid `temporal`, `reference` or `timezone` | Error `invalid_temporal_mode`, `invalid_reference` or `invalid_timezone` | Same |
| Event-time lookup fails in the database | Original order, warning `temporal metadata unavailable — original order kept` | Error `temporal_metadata_unavailable` (CLI exit 3); never an unfiltered result |

A failed lookup is rolled back to a savepoint, so the caller's transaction stays
usable.

## Limits

Temporal search reorders or filters at most the 150 retrieval candidates and 20
graph nodes the existing search already selected. `filter` guarantees the period
on every returned hit; it does not find older matching documents that were never
candidates, and it is not a historical snapshot. The grammar is fixed and English
or German only. No model, provider or network call is made. Measured on the
synthetic benchmark, a search with an applied period took a median of about 28 ms
longer than without (p95 about 55 ms); searches without a period showed no
measurable difference. See the
[benchmark](benchmarks/2026-10-31-temporal-query/README.md) for the full numbers.

## Configuration

```toml
[temporal]
enabled = false        # true: auto behaves like prefer when a period is recognized
timezone = "UTC"       # default zone for calendar days, IANA name
```

Both keys are optional. An invalid zone stops configuration loading with
`invalid_timezone`. Clients of a central service do not need the section: the
server's setting decides `auto`.

## Enable, check and roll back

Upgrading from 0.6.16 needs no migration, data rewrite or re-embedding; the store
stays on schema029. The existing operator upgrade workflow also accepts
`--source-version 0.6.16`; its verified backup/restore and preservation checks
remain available even though no migration is applied.

1. Install 0.6.17 and restart long-running processes (`rag service serve`, MCP
   servers) so they load the new code and tool signatures.
2. Try one search explicitly, without changing the configuration:
   `rag search "backup failed gestern" --temporal prefer --timezone Europe/Berlin --json`.
   The output now contains a `temporal` object with `status: "interval"`.
3. To make `auto` use it, add `[temporal] enabled = true` (and your `timezone`)
   to the configuration of the process that runs searches, then restart it.
4. Run the same search without `--temporal`. The `temporal` object shows
   `requested: "auto"` and `mode: "prefer"`.

To roll back, set `enabled = false` or remove the section and restart; results
are again identical to 0.6.16. Reinstalling 0.6.16 is also safe: it ignores the
`[temporal]` section and reads the same data. A 0.6.17 client only sends the new
arguments when you set them; a 0.6.16 server rejects them with
`invalid_arguments` instead of silently ignoring them.

In client mode (`[service] mode = "client"`), `rag search` now runs on the
central service, like `rag evidence`, instead of trying a local database.

## Terms

- **Period**: the interval a recognized expression stands for.
- **Event time**: the assertion event time or a qualifying source time, never an
  import time.
- **Qualifying source**: an active source that alone could make the claim
  eligible (operator-reviewed for a confirmed claim, or a complete user statement
  for a stated claim).
- **Candidate-limited**: the stage only sees what retrieval already selected.
