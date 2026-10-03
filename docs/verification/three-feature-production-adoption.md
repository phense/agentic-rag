---
id: three-feature-production-adoption
title: Local production adoption of retrieval features 1–3
type: reference
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: ae4a102 from 0c8addd
depends_on: []
assets: []
last_reviewed: 2026-10-03
summary: Verified local deployment, recovery evidence and client adoption limits for PRs 36, 38 and 39.
---

# Local production adoption of retrieval features 1–3

## Overview

On 2026-10-03 the maintainer authorized merging PR #39 and adopting all three
retrieval PRs in the existing local production installation. The production
checkout advanced from `0c8adddfaf96e105990019eef0b664c7e29ceade` to
`ae4a10283a8cd17525fc0550c9c5b4398679ea39` after backup verification and independent
deployment review. One canonical PostgreSQL + pgvector store remains in use.

## Deployment record

| Element | Verified result |
| --- | --- |
| Approved implementation PRs | [#36](https://github.com/phense/agentic-rag/pull/36) (`f27acd9`), [#38](https://github.com/phense/agentic-rag/pull/38) (`342bccf`), [#39](https://github.com/phense/agentic-rag/pull/39) (`ae4a102`) all merged |
| Existing installation | Source `0c8addd`, migrations001–014, retained Python3.13.12 environment |
| Change applied | Clean checkout advanced with `git merge --ff-only ae4a10283a8cd17525fc0550c9c5b4398679ea39`; worker singleton lock held only during that transition |
| Preserved components | Schema, dependencies/lock, Ollama, embedding model, mining provider, hooks and client settings unchanged |
| Configuration evidence | All five production/client configuration files remained byte-identical; private copies and SHA-256 values retained |
| Backup | 60.8MiB custom-format `pg_dump`, using an exported repeatable-read snapshot; SHA-256 recorded privately |
| Restore rehearsal | Restored with `pg_restore --clean --if-exists --single-transaction` into a randomly named, ownership-checked scratch database; every row of all16 production public tables matched the snapshot fingerprints; scratch dropped |
| Post-deployment data check | Every row of all16 production tables still matched the pre-deployment snapshot fingerprints; no persisted migration or test knowledge write |
| Retained knowledge | 10,395 documents, 11,785 chunks, 22 pins, 20 checkpoints, 26,332 audit rows; queue1,387 rows and all other tables also unchanged at verification |
| Fresh full-suite checks | `/Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`: **930 passed in37.41s**; `node --test tests/test_opencode_plugin.mjs`: **7 passed** |
| CLI consumer check | Absolute installed `rag search` called from the Trading directory; eligible exact result and original citation span verified |
| Fresh read-only MCP | Real stdio initialization, seven tools, no write tools, additive `strategy`/`rerank` search fields, successful scoped exact search |
| Fresh authorized MCP | Real stdio initialization, thirteen tools including audited gateway tools, same additive search fields, successful scoped read; no production write invoked |
| Worker singleton | Released after checkout transition and successfully reacquired after verification |
| Independent deployment review | Complete staged service/configuration and evidence review: Ready, zero unresolved Critical/High/Medium/Low findings |

Table fingerprints include row counts and a SHA-256 of the sorted collection of
individual JSON-row hashes, preserving duplicate multiplicity. Snapshot and
restored fingerprints were compared exactly. Private source text, identifiers,
credentials and database dumps are excluded from repository artifacts.

## Local model service

| Element | Verified result |
| --- | --- |
| Weights | Qwen3-Reranker-0.6B Q8_0, ggml-org revision `a02f48bb4f057028298c21fa033da2b30d7742d5`,639,153,184bytes |
| Weight SHA-256 | `22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48` |
| Native runtime | llama.cpp b9840 (`8c146a836`), copied with companion resources to `~/.agentic-rag/runtime/reranker-b9840`; executable hash matches the validated original |
| Durable supervision | New `com.agentic-rag.reranker` user LaunchAgent, automatic startup/restart,30-second restart throttle; existing Ollama supervisor untouched |
| Network and privacy | Listener verified at literal `127.0.0.1:8766`; offline mode, web UI disabled, request logging disabled; stdout/stderr discarded |
| Identity check | `/v1/models` advertises exact alias `agentic-rag-qwen3-reranker-0.6b-q8` |
| Synthetic discrimination | German capital-of-China query: English Beijing passage score0.996112; Paris passage0.000029; finite indexed scores and correct ordering |
| Supervisor restart | `launchctl kickstart -k` of only the new reranker succeeded; model identity and discrimination passed afterward |

The existing on-disk backup/maintenance files contained JSON argument arrays,
although their loaded jobs remained healthy. Their private before-state and loaded
definitions were retained. Valid plists now reproduce the loaded executable,
arguments, log paths and schedules: backup03:30, maintenance04:00. Existing loaded
jobs were left running with those same definitions; both last exit codes were0.

## Practical live checks

| Scenario | Original ordering | Neural ordering | Verification |
| --- | --- | --- | --- |
| Related Trading concepts | 1/2 expected sources | 2/2 | Scoped results and original source spans valid |
| German question, English sources | 1/3 | 3/3 | Scoped results and original source spans valid |
| Ambiguous newsletter failure | 2/3 | 3/3 | Scoped results and original source spans valid |
| Three repeated MCP questions with neural stage off | First1061.988ms; repeats812.897/810.852ms | One embedding invocation across three calls | Identical citation lists; fresh SQL still executes each time |
| Exact UUID/slug | 50.865/45.565ms live smoke samples | Neural inference bypassed | Intended eligible source found with original citation spans |

These are single live smoke checks. Neural-off calls precede auto calls and warm
the query cache, so their latencies are not a paired benchmark. Source coverage
uses the previously read private labels at k=3; it does not establish general
answer accuracy. [Aggregate smoke output](three-feature-production-adoption.json)
contains no private queries or source identifiers. The original repeated
measurements remain the attributable feature comparisons:
[adaptive search](../benchmarks/2026-10-03-adaptive-search/README.md),
[query cache](../benchmarks/2026-10-03-query-cache/README.md), and
[neural reranking](../benchmarks/2026-10-03-neural-rerank/README.md).

## Limits and recovery

Already-running Claude/Codex stdio processes retain imported code until
client-controlled reconnect or a new session. They can coexist with the new
processes against the same canonical store. Parent sessions were not terminated.
Fresh CLI/hook/job invocations and newly initialized MCP clients use the updated
checkout. This record verifies fresh MCP clients, not an interactive reconnect of
every pre-existing client session.

The optional model adds roughly one second on the measured ambiguous questions
and consumes approximately1.17GiB after the small synthetic request. Other
queries retain deterministic routing or hybrid ordering. Runtime capacity remains
an operator responsibility; the adapter keeps its documented candidate and
deadline bounds. See [runtime operation and fallback](../local-reranker.md).

Private recovery artifacts are retained in
`~/.agentic-rag/deployments/2026-10-03-three-features/`: source archive, configuration
copies, consistent database dump, fingerprints, loaded job definitions, smoke
records and `ROLLBACK.md`. Code rollback uses the preserved source with the
unchanged Python environment and canonical database. Stopping only the optional
reranker retains ordinary ordering. A database restore is disaster recovery and
would lose writes made after the snapshot; it is unnecessary for code rollback.
The malformed original schedule files must not replace the repaired valid plists.

Existing dependency advisories remain open in [#37](https://github.com/phense/agentic-rag/issues/37).
[Applicability triage](https://github.com/phense/agentic-rag/issues/37#issuecomment-5970177456)
checked all16 alerts against deployed stdio, authentication, subprocess and local
HTTP paths; those reported vulnerable paths are inactive in this installation.
No package was upgraded and no alert dismissed. Patched isolated-environment
verification and remediation remain separate work.
