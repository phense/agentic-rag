# RAG-5.9 verification record

Implementation verification is complete; merge and production adoption remain pending.
Source1294d6c44fd02b66715692f12791bfa2fd4c8856/schema018. Measured code88c1c36f2fe6f3145d290a6de141e65914acc403/schema019. Documentation/evidence commits after that revision do not alter measured code. [Raw evidence and limits](../benchmarks/2026-10-04-incremental-ingestion/README.md).

## Fresh suites

`/Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`:1169 passed in151.59s.
`node --test tests/test_opencode_plugin.mjs`:7 passed in79.447292ms.
Behavioral red tests preceded the new cache module. Subsequent regressions first failed on unguarded child ownership/config handling before their fixes.

## Reviews and disposition

Two independent complete bounded code/PB reviews at88c1c36 found no remaining Critical, High, Medium or Low bugs. Both independent final public artifact audits verified all114 frozen code hashes, raw20-pair statistics/denominators and executed operational evidence. Results SHA-256:914a17cc699aa0734ee808ea47f96023217e3867cc3b8934177b3ba21e91023a. Two Low documentation errors (queue median and production-write wording) were fixed and rechecked. Reviewers used public code only; no private dump/corpus/config was shared.

Verified findings fixed: fallback escaped the shared concurrency semaphore; reuse counters mixed persisted hit occurrences and prepared consumption; child config omitted model/dimension; child mode lacked preconnection ownership protection; backup identity omitted the actual PostgreSQL cluster/database/endpoint; checkout drift was not checked immediately before activation/recovery; run-level model identity was not frozen; backlog/edit oracles omitted complete literal input/vector/cursor checks; asymmetric after-only fault fixtures contaminated paired state. The obsolete Trading source label was corrected. No unresolved Low finding remains.

Historical first full run exposed old migration-list expectations and a query-only metadata counter that included ingestion; source/query assertions remain intact. Prototype oracle failures were fixture trailing whitespace and an incorrectly authored queue EOF cursor, corrected against unchanged parser/window contracts. Final content/cursor/vector checks passed all20 pairs.

## Rehearsed operations

Unified driver:20 paired observations for each of three scenarios; real local embeddings, frozen model/code hashes; zero hosted calls/production application writes. Actual process deaths before queue ack and during uncommitted accepted application recovered original documents once.

Populated synthetic018→019: strict source/target restores, DDL rollback/retry/no-op, pins/checkpoints/queued work/grants/original rows retained, candidate save on018, old/new CLI and10/18 MCP contracts, persistent simultaneous source/candidate writer transactions on018 and019. Owned Git activation, schema-committed retry and detached source-code recovery retaining019 succeeded. Eight actual guard rejections cover abbreviated target, wrong backup database/server identity, expired backup, dirty/drifted source, busy worker lock, post-lock drift, post-migration drift and pre-recovery drift.

Fresh populated production018 backup/strict owned restore, interrupted019 migration/retry/no-op and exact original row/grant retention succeeded without modifying production. Public aggregate inventories and read-only Trading source controls are in results.json. All private state stays outside Git. This is an executed recovery rehearsal, not production rollout evidence.

PB-5.9 remains executable for the separately approved exact target. Application/cache writes stay within original audited gateways. Code recovery retains019 and later knowledge; restoring a backup would lose later writes and requires separate authority. Existing active MCP processes must reconnect after a separately authorized activation to load new code. No service interruption, configuration rewrite, provider change or editable reinstall occurred.

[PR47](https://github.com/phense/agentic-rag/pull/47) is published and linked to this thread. Remote offline benchmark-contract CI passed (runs37169239028 and37169241717,12s/15s); merge/adoption remain pending. Both complete reviews found no open Critical/High/Medium/Low bugs.
