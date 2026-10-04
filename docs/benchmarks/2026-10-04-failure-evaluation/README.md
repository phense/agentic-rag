# Confirmed failures: paired offline retrieval and public mining measurements

Measured code: `5b390692e32e07c8816e98091dfa66e15e0c2cb3`, based on reviewed
Feature9 `d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d`. Both retrieval profiles use
that same compiled application revision: unchanged ordinary hybrid search
`search-title-0` versus development-selected existing entity routing `entity-title-0`.
This compares offline policies, not two deployed versions. No candidate changes live policy.

The authored public corpus has204 documents and96 queries. Six whole source/alias/history
families supply48 development queries; six independent held-out families supply48 test
queries. Literal entity, attribute, domain, project and time selectors are caller inputs;
expected values/IDs never enter retrieval. Both profiles see identical indexed originals,
4000-character budgets and the same original-source extractive answer checks.

## Three practical before/after examples

| Scenario | Ordinary route | Selected route | Sample and outcome |
| --- | --- | --- | --- |
| Unanswerable memory-limit question | Irrelevant candidates in12/12 cases; mean3910 context characters | Irrelevant candidates in0/12; empty context | Twelve EN/DE queries across six families. Both correctly abstain12/12; abstention quality was already correct. |
| Renamed service with current correction, independent projects/domains | Current answers6/18; independent-boundary answers6/12 | Current answers18/18; independent-boundary answers12/12 | Original-supported exact values and IDs, not confidence labels. Historical answers remain6/6 on both routes; wrong-scope/stale output0 on both. |
| Explicit user port correction versus assistant/hypothetical suggestions | Held-out user corrections2/2, unsafe accepted facts0 | Corrections2/2, unsafe0; source prompt retained | Eight actual configured native calls total; two independent held-out families and two dev families. Additional prompt gave no measured quality gain. |

For example, the old service name has no current literal status assertion after its
confirmed rename. Ordinary search can retrieve plausible notes but the literal answerer
withholds a current value; confirmed alias routing returns the new name's original
`running` evidence. The independent project returns its own `maintenance` original.
An independent programming-domain status `compiling` is suppressed by an existing
cross-domain temporal eligibility defect on ordinary search and recovered by exact
entity routing. That pre-existing gateway/SQL defect remains open as
[Issue48](https://github.com/phense/agentic-rag/issues/48); this feature does not repair it.

| Held-out group | Baseline p50/p95 ms | Candidate p50/p95 ms | Timing observations per route |
| --- | ---: | ---: | ---: |
| All48 queries | 223.982/246.363 | 44.0895/53.179 | 960 |
| Unanswerable12 | 230.6705/248.121 | 41.8405/51.930 | 240 |
| Current correction18 | 227.788/247.170 | 44.3075/54.562 | 360 |
| Independent boundaries12 | 196.7115/209.476 | 42.6405/49.834 | 240 |
| Historical6 | 226.4245/245.381 | 47.0305/54.596 | 120 |

Overall exact supported correctness is30/48→48/48; positive evidence recall24/36→36/36.
False abstention is18/36→0/36. Mean context is2764.375→102.750 characters, with token
estimates691.4583→25.750 (`ceil(chars/4)`, not measured model tokens). All original
citations are rehydrated and checked; repeated source/value/context outcomes are stable.
Every indexing/query error remains counted; this run has0 of either.

Each held-out query has20 alternating route pairs in one process. First calls are
included; PostgreSQL/Ollama/OS caches remain retained. Databases are fresh per split,
not per timing repeat. These are not cold-service measurements. Query timers exclude
model-identity checks; indexing timers include them. The development grid runs once
per profile; repetitions do not enlarge truth denominators. Six synthetic families
repeat the same structural patterns, so the family bootstrap intervals collapse to
[0.625,0.625] and[1,1]; they establish no uncertainty bound for real traffic. General
language-model answer accuracy remains null. Wider-visible global/ancestor corpora
require separate exact-boundary queries and are rejected before service work.

## Indexing and native-provider cost

Development and held-out indexing each retain102/102 originals,102 original chunks
and102 non-null vectors, with zero failures. Times are21449.574ms and21516.726ms.
The compared profiles share those indexes; no candidate indexing-cost reduction is
claimed. Local `bge-m3` digest:
`7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`, dimension1024.
The endpoint hash, digest, model and source bytes are frozen and checked throughout.

Native mining uses the existing `codex` provider/model `gpt-6.1-sol` in its empty,
ephemeral transform directory, with built-in public transcripts only. Development
compares two static prompts: the source obtains1/2 accepted user corrections and the
extra prefix0/2, with zero unsafe accepted facts. Three development outputs are retained
with review disposition and counted as misses; no provider error is discarded. The
better development recall retains the unchanged source prompt. Held-out baseline and
candidate therefore use identical prompts and per-family inputs. Each excludes both
prohibited suggestion statements, retains one resulting chunk with its vector, and
replays its accepted result without another model call or duplicate application.

The two baseline observations are14311.337/12378.314ms; candidate observations are
11898.948/11272.009ms. With only two independent families and unchanged prompts,
these differences are run variation, not a prompt latency gain. Each held-out call has
3614 prompt characters. Billing/token cost and the hosted backend's immutable revision
are unavailable; no statistical/general prompt-quality gain is claimed.
[Native raw results](mining/results.json), [dev-only prompt candidate](mining/candidate.json).
Only that dev artifact is supplied to retrieval optimization; native held-out results
are separate and cannot select its profile.

## Existing-installation and private-label controls

The unified driver executes actual populated018→019 interrupted DDL/retry/no-op,
strict source/target restore, guarded owned Git activation/retry/detached recovery,
old/new CLI and fresh10-reader/18-main MCP contracts with persistent overlapping
uncommitted writers. The source019 code-only path uses the same operator helper as
PB-5.10; it retains019, original rows/grants/later writes and branch refs. Three extra
code-only unsafe conditions reject before Git: dirty checkout, busy worker lock and
schema-time checkout drift. The combined path also executes its eight rejection cases.

A controlled provider-free private-format rehearsal uses audited public corrections
and aliases, requires both actual whole-family splits, excludes assistant/unreviewed/
incomplete negatives, rechecks private candidate bytes/modes/seal and compares full
original table inventories including audit before/after read-only export/evaluation.
Only aggregate counts leave private files. Its final counts and strict production-copy
restore/retry controls are in [results.json](results.json); private dumps/labels never
enter Git or a provider. Trading controls are live018 lexical reads with original
citations checked; their timings do not measure a live Feature10 policy gain.

## Reproduce and evidence

Run a clean checkout of the measured commit with the original interpreter. Use new
paths. Native calls are explicitly requested; production-copy/Trading options perform
read-only canonical sampling and all restore/migration/fault work on owned copies.

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_failure_evaluation.py \
  --output docs/benchmarks/new-failure-evaluation \
  --private-dir /absolute/private/new-directory --repeats 20 \
  --mine-model --production-copy --trading
```

[Unified raw evidence](results.json), [retrieval results](evaluation/results.json),
[dev results](evaluation/dev-results.json), [held-out results](evaluation/heldout-results.json),
[sealed retrieval candidate](evaluation/candidate.json), [operator procedure](../../playbooks/failure-evaluation.md),
[verification and review dispositions](../../verification/failure-evaluation.md).
