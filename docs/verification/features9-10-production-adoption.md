---
id: features9-10-production-adoption
title: Features 9 and 10 production adoption
type: reference
doc_id: standalone
readers: [operators, maintainers]
status: accepted
version: 0.6.0
depends_on: []
assets: []
last_reviewed: 2026-10-04
summary: Executed approved schema018→019 adoption, protected production state and fresh client acceptance.
---

# Features 9 and 10 production adoption — 2026-10-04

The maintainer explicitly approved merging PR47/49 and applying them to production.
Both PRs merged with their reviewed exact heads; the canonical installation then
advanced from source018 to their combined merged target through the unchanged,
reviewed [PB-5.9](../playbooks/incremental-ingestion.md) activation helper.

## Source and adopted target

| Item | Executed value |
| --- | --- |
| Canonical source | `1294d6c44fd02b66715692f12791bfa2fd4c8856`, schema001–018 |
| PR47 reviewed head / merge | `d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d` / `eb655601ca95dc8dca11e20a64a4415daca7be36` |
| PR49 reviewed head / merge | `113e74d7e0dba2752a41f1008252488815097dfb` / `b849d3423a51a5d0f90273c3d5ed88433ec78778` |
| Adopted code | `b849d3423a51a5d0f90273c3d5ed88433ec78778`, schema001–019 |
| Interpreter | Existing canonical `.venv/bin/python`; no environment redirect |
| Migration | Only `019_embedding_reuse.sql`, additive and atomic |
| Worker exclusion | Immediate singleton lock acquired; released and independently reacquired |
| Fresh main/reader MCP | 18 / 10 tools, write-tool registration present only for main |

PR49 was retargeted from the Feature9 branch to main after PR47 merged. Its head
remained unchanged; both hosted CI checks passed. The combined merge tree is exactly
the reviewed Feature10 tree. A separate clean candidate at the full combined target
provided code and SQL; the canonical source remained untouched until activation.

## Strict backup and retained state

A new private0700 directory held source018 dump/report and protected inventories;
files were created exclusively with0600. `verified_backup` exported one consistent
read-only PostgreSQL snapshot for both dump and inventory, strictly restored it with
`--single-transaction --exit-on-error` into an owned blank database, compared every
public table/row and application table grant, then verified owned cleanup. The
activation helper checked actual cluster/database/connection identity, dump checksum,
permissions, fresh report age, clean checkouts and imported candidate module/SQL paths
before and under the worker lock. Private content, configuration values and backups
remain outside Git.

| Source018 inventory at backup | Retained rows |
| --- | ---: |
| Public tables, including migration ledger | 21 |
| Documents / original chunks | 10632 / 12022 |
| Domains / pins | 7 / 22 |
| Continuation checkpoints / queued work | 35 / 1420 |
| Accepted mining batches / audit history | 1028 / 39099 |

Post-activation comparisons retain every original primary key and every original
source/evidence/history row. Already-applied batch results are unchanged; previously
accepted extraction, domains, cursors, project, warnings and creation time remain.
Queue identity and original input selectors are protected while derived progress/rerun
fields may change. Checkpoint lineage is protected while normal state/enrichment may
advance. The initial check found zero changed operational rows; the final strengthened
check found one normally updated checkpoint with its protected lineage unchanged.
All original source rows and grants are unchanged. Eight captured configuration/scheduler files retain their original hashes. The ninth,
Claude’s client JSON, refreshed runtime feature/usage caches after the initial
all-nine hash check. Its pre-change bytes were recovered from a client backup by
matching the original SHA256. Type-preserving canonical JSON comparison excludes
only `cachedGrowthBookFeatures`, `cachedGrowthBookFeaturesAt` and
`cachedUsageUtilization`; all settings remain unchanged. This inventory is limited to the captured paths. Activation called no
installer and changed no client configuration, hooks, jobs or provider selection.
The new derived cache was empty at acceptance; no legacy vector backfill was attempted.

A strict target019 restore is recorded after activation. It verifies all22 public
tables/rows and application grants, with owned cleanup. Production was never restored,
reset or interrupted. Code recovery was already executed on representative owned
copies using the same helper, with019 and later writes retained; those
[Feature9](incremental-ingestion.md) and [Feature10](failure-evaluation.md)
rehearsal records remain distinct from this production acceptance.

## Executed acceptance

| Command or probe | Result |
| --- | --- |
| Candidate original interpreter + `scripts/activate_incremental_ingestion.py --canonical <canonical> --candidate <clean-combined-candidate> --approved-target b849d3423a51a5d0f90273c3d5ed88433ec78778 --verified-dump <new-private-dump> --backup-report <strict-private-report>` | Exit0; exact adopted revision, schema19, worker lock released |
| `PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q` | 1274 passed in176.79s; destructive tests use the isolated test database |
| `node --test tests/test_opencode_plugin.mjs` | 7 passed in88.316667ms |
| Source018 code and adopted code, each on retained019 | Three lexical Trading queries, 5 results/query; all15 citations identical and original chunk offsets checked |
| Fresh source/adopted MCP processes, each reader and main | Four clients;10/18-tool contracts and real `memory_search`/`memory_get` pass |
| `rag benchmark --help` | New optimize, export/evaluate-corrections and optimize-mining commands discoverable |
| Independent bounded operational review | No remaining Critical/High/Medium/Low findings in activation and strengthened acceptance probes |

The probes used `portfolio risk`, `earnings announcement` and `market regime`.
They made zero provider calls or production application writes. The read-back inventory
and strict restores used owner read-only snapshots; schema019 was the only production
DDL. Existing sessions can keep source code on019; fresh or reconnected MCP clients
load adopted code. No process/service was terminated.

## Measurement and remaining limits

The original [Feature9 measurements](../benchmarks/2026-10-04-incremental-ingestion/README.md)
and [Feature10 measurements](../benchmarks/2026-10-04-failure-evaluation/README.md)
retain their measured source revisions, raw values and sample sizes. This production
acceptance validates upgrade/state/client contracts, without claiming a production
latency or model-quality improvement. No benchmark candidate changes live search or
mining policy. Existing domain-free temporal comparison remains separate
[Issue48](https://github.com/phense/agentic-rag/issues/48).
