# PB-5.4: Review and rehearsal evidence

## Scope

- Playbook: [contextual-indexing.md](../contextual-indexing.md), dated2026-10-03.
- Source: `499c656`; actual001–014 SQL and old `store.py`/`search.py` loaded from Git.
- Target: candidate file SHA256 values in [results.json](../benchmarks/2026-10-03-contextual-indexing/results.json); additive015.
- Owner: Feature 4 coordinator; AC-002–007. Required level: executable isolated populated migration, interruption, retry, mixed clients, backup restoration and numerical evidence before merge.

## Content review

Independent reviewer: `/root/review_contextual`. Initial review found four Medium defects (query/model race, queued retry losing context, CLI required-field exit code, architecture-history deletion); all fixed with regression evidence and verified in the second pass. Final review additionally identified a queued-reembed concurrency scenario and an insufficient legacy backup-verifier gate; the race was reproduced and fixed, and a strict shared-snapshot backup/restore helper replaced that acceptance gate. The pending-output documentation Low mismatch was fixed. Final complete-diff review and PB-5.4 content review: **Ready**,2026-10-03. No unresolved Critical, High, Medium or Low findings. Reviewer independently checked all seven measured app/SQL/script SHA256 values against current bytes; did not run shared DB tests or mutate production.

## Rehearsal

Executed2026-10-03 using [script](../../scripts/verify_contextual_indexing.py), local PostgreSQL and existing bge-m3. All writes went through audited gateways in randomly named owned databases. Production authority was read-only only. Detailed full-row fingerprints, model digest, source hashes, measured costs and paired outcomes are in the numerical artifact.

Fresh full suite: 960 passed 36.85s; Node7 passed. Thirty feature behavior tests include current-source reembed revalidation and lock conflicts.

Covered: strict shared-snapshot operator backup with every public row and role/table privileges checked; populated014, new writer on014, transactional015 interruption/retry/idempotence, canonical preservation, bounded audited CLI indexing, original reader MCP citations, old writer correction during partial progress, source/scope refresh, actual old reader/code rollback, separate014 backup restore and reupgrade, ownership-checked cleanup.

The first attempted in-place014 restore over015 failed because the new derived-table FK prevented dropping the old chunk PK. The supported recovery path was corrected to a separate owned014 target, with every canonical fingerprint checked after restore and after reupgrade. This does not authorize any production restore/cutover.

Unmeasured: derived-index search at full Trading scale, sustained model replacement/load, production migration lock duration, real production cutover. Synthetic measurements use three authored cases; twenty repeats per route quantify timing/repeatability rather than independent question diversity.

## Acceptance and freshness

Playbook drafted, independently reviewed Ready and rehearsed successfully. Full fresh960 Python/7 Node verification passes. Feature implementation readiness is satisfied; [PR42](https://github.com/phense/agentic-rag/pull/42) is submitted; its specific merge and production rollout approval remain pending. Root production remains499c656/schema014. CLI continuity tooling cannot parse this repository's legacy numbered BACKLOG; current Git, artifact paths, live reviewer identity and canonical Issue #29 OPEN were manually revalidated. No CLI recovery success is claimed.

## Final review dispositions and convergence

| Finding | Resolution | Verification |
| --- | --- | --- |
| Medium: query model race | pre/post identity binds contextual query vectors | A→B regression |
| Medium: queued retry context loss | lexical context rebuilt in the existing transaction | outage→reembed regression |
| Medium: ordinary CLI required arguments | argparse exit2 before config/DB | invalid ordinary save regression |
| Medium: architecture history deletion | prior findings retained; Feature4 appended | bounded history diff |
| Medium: queued source race | NOWAIT lock/revalidate title/body before replacement, rollback on conflict | concurrent correction red→green |
| Medium: weak backup acceptance | strict exported-snapshot dump/empty owned restore/full-row and privilege comparison | strict_operator_backup artifact |
| Low: empty pending JSON description | doc_id documented only when a target exists | CLI/docs source review |

Legacy maintenance verifier hardening remains separately tracked in [Issue41](https://github.com/phense/agentic-rag/issues/41), outside the Feature4 bounded implementation; Feature4 no longer relies on that verifier for upgrade acceptance. No nonblocking Low bug was deferred.

AC-001/002: grounded builder/fence/bounds tests plus every measured original span/citation. AC-003: side-only indexing, all15 canonical fingerprints and retained historical audits. AC-004: source/model/lock/reembed regressions and partial old-writer recovery. AC-005: writer-only grants, project/domain/status/time tests and reader MCP. AC-006: actual014 new-code/save fallback, additive/idempotent015 and actual old clients/code rollback. AC-007: three practical paired examples, separate costs, raw evidence, full suites and final independent review. FR-001–004 and IC-001–003 match the as-built model. No actionable convergence gap in implementation; merge and deployment remain distinct lifecycle gates.

Reviewed playbook SHA256: `d45dd02e060c64f6b272be808ad9ffa59373ce1f23e84c7eef19f26e211957a0` (PB-002 wording aligned to the strict helper after the reviewer’s editorial note).


## Production adoption

The preceding sections preserve the pre-merge review record. On2026-10-03 the maintainer separately approved merge and local rollout. [PR42](https://github.com/phense/agentic-rag/pull/42) merged as99514fe012666e67dff02ae2419e05a6c876d1f9; the canonical checkout fast-forwarded and015 was applied additively. The complete audited backfill indexed10432 documents/11822 chunks in2565.82s, with0 retries/warnings and10439 index audit records. All12 protected canonical knowledge-table fingerprints and26545 historical audit row hashes were retained, as were21 existing checkpoints,1391 existing queue IDs and22 pins; normal concurrent sessions could add checkpoint/queue rows.

Both source014 and converted015 dumps were strictly restored to empty owned targets and compared across every public table and application table privilege. Fresh CLI and both MCP privileges passed; adapters, dependency installation and services stayed unchanged.960 Python/7 Node checks and final independent review passed. [Issue29](https://github.com/phense/agentic-rag/issues/29) is closed with the complete rollout evidence. Private inventories/dumps/reports are retained under `/Users/peter/.agentic-rag/state/contextual-rollout-20261003T164229Z`; no private payloads are published here.

Twenty paired full-scale controls: exact15.394→15.287ms, empty lexical18.798→26.796ms, question449.353→615.142ms (36.9% overhead). Original citation lists were20/20 identical for old/context-off controls; question routes each validated60 citations. These results do not demonstrate a production quality gain or a universal speedup. Existing long-lived MCP processes adopt code after reconnect.
