# PB-5.5: Upgrade an existing store to filter-aware retrieval

## Identity and scope

- Class: both; system upgrade and development acceptance for RAG-5.5 AC-006.
- Origin: [Issue30](https://github.com/phense/agentic-rag/issues/30), [spec and source version](specs/RAG-5.5-filter-aware-search/spec.md).
- Audience: operator of an existing multi-user PostgreSQL store; accountable owner: maintainer Peter.
- Target: source `99514fe012666e67dff02ae2419e05a6c876d1f9`, schema001–015; target code containing016. The tests also cover new code on015 and old code on016.
- Deadline: content review and populated isolated rehearsal before PR readiness; separate specific merge and production-deployment approvals before the respective operations.
- Last edited: 2026-10-03.
- [Review and rehearsal evidence](verification/filter-aware-search.md).

## When to use / when not to use

Use for adopting the planned default semantic search on an existing015 store. Migration016 adds four invoker read functions. It does not rebuild indices, convert knowledge, re-embed chunks, change providers, update configuration, or alter write gateways. Old search functions remain available.

Do not apply this procedure to an unverified source version, a store missing015, a different embedding dimension, or an extension older than the existing halfvec schema supports. Do not reset the schema or run initialization to repair a failure. Installing/upgrading PostgreSQL or pgvector is outside this procedure. Iterative scanning is detected when the installed extension supports it; no extension upgrade is required.

## Before starting

The operator needs the source checkout and approved candidate checkout, the existing absolute Python executable, local PostgreSQL owner access, working `pg_dump`/`pg_restore`, free space for a private dump plus an isolated restore, and explicit rollout authority. Keep source and candidate dependency environments intact. The canonical production executable is `/Users/peter/Agents/agentic-rag/.venv/bin/python`; before adoption, select candidate imports with `PYTHONPATH` rather than reinstalling that shared editable environment.

Intentional inputs below: `CANDIDATE` is the absolute approved checkout path, `PRIVATE` is a new absolute private evidence directory, and `SOURCE_REV` is the exact pre-upgrade code revision recorded by PB-001. Export these with ordinary shell quoting. No credentials belong in command arguments or evidence.

For this repository the isolated rehearsal checkout is `/Users/peter/Agents/agentic-rag/.worktrees/adaptive-search`; production is `/Users/peter/Agents/agentic-rag`. A worktree path is not a deployment target.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
| --- | --- | --- | --- | --- |
| PB-001 | Operator, source checkout/store | Read `git status --short`, exact HEAD, installed migration filenames and extension version. Check015 is present,016 absent, and the candidate adds only016 to these installed migrations. Record model identity and client privileges. | Clean supported checkout; source revision and schema identified; unchanged model/configuration. | Unexpected pending migration or local edit: stop; maintainer resolves scope. |
| PB-002 | Operator, source store/private owned target | Before deployment, capture a consistent private dump and strictly restore it to an empty owned database. Compare every public table and role/table privilege. | Strict helper reports all rows and privileges match; ownership cleanup verified;0600 dump retained outside Git. | Nonzero restore, partial inventory, insufficient disk or mismatch: stop. Ordinary maintenance backup verification is not this gate. |
| PB-003 | Operator, isolated owned stores | Execute synthetic upgrade/recovery rehearsal and Trading snapshot-copy controls using commands below. Review measured latency/recall, all protected table fingerprints and original citations. | Actual015→016 retry/idempotence, old/new readers/writer, code rollback and preservation proof. | Failed acceptance or material latency regression: stop; implementation/review loop. |
| PB-004 | Operator, production checkout | Only after specific PR merge and rollout approval, fast-forward the clean checkout to the approved merge commit. Retain `SOURCE_REV` and backup. Do not reinstall dependencies or adapters. | Approved code deployed; no unrelated local edit or setting changed. | Cannot fast-forward: stop and reconcile; do not force-reset production. |
| PB-005 | Operator, existing production store | Apply pending migrations on a dedicated owner connection using `db.apply_migrations`, only after PB-001 confirmed exactly016 pending. Set transaction-local lock and statement budgets as shown. | Exactly `['016_filter_aware_search.sql']` applied atomically; subsequent retry returns `[]`. | Lock/statement cancellation: close connection (rollback); keep source evidence and retry in a quiet interval. No force termination of clients. |
| PB-006 | Operator, existing clients/store | Open fresh reader and authorized writer MCP/CLI sessions; verify known project/domain queries, original citations and unchanged knowledge/audit/history inventories. Existing MCP processes adopt Python changes on reconnect. | Original source citations, access boundaries and protected pre-existing rows retained; normal audited concurrent additions accounted for. | Unusable clients, changed boundaries or unexplained lost rows: stop rollout and use code rollback; investigate before resuming. |

PB-002, using candidate code only for the strict helper; this performs source reads and writes exclusively to owned restore targets:

```sh
mkdir -m 700 "$PRIVATE"
PYTHONPATH="$CANDIDATE" /Users/peter/Agents/agentic-rag/.venv/bin/python "$CANDIDATE/scripts/verify_contextual_indexing.py" --verified-backup "$PRIVATE/source015.dump" --output "$PRIVATE/backup-report.json"
```

PB-003 creates its private subdirectories itself and refuses existing paths. Trading production is read-only;016 and all tests operate on disposable copies. Reports contain aggregates and hashes; private dump contents must never be committed:

```sh
PYTHONPATH="$CANDIDATE" /Users/peter/Agents/agentic-rag/.venv/bin/python "$CANDIDATE/scripts/verify_filter_aware_search.py" --repeats 20 --private-dir "$PRIVATE/synthetic" --output "$PRIVATE/rehearsal.json"
PYTHONPATH="$CANDIDATE" /Users/peter/Agents/agentic-rag/.venv/bin/python "$CANDIDATE/scripts/verify_filter_aware_search.py" --trading-copy --repeats 20 --private-dir "$PRIVATE/trading" --output "$PRIVATE/trading.json"
```

PB-005, from the deployed production checkout. This deliberately does not call `init_db`; preflight must have identified the existing store and exactly016 pending:

```sh
/Users/peter/Agents/agentic-rag/.venv/bin/python - <<'PY'
from agentic_rag import db
from agentic_rag.config import load_config
with db.connect(load_config(), role='owner') as conn:
    conn.execute("SET LOCAL lock_timeout='2s'")
    conn.execute("SET LOCAL statement_timeout='30s'")
    installed={r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations')}
    pending=[p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name not in installed]
    assert '015_contextual_chunks.sql' in installed
    assert pending in (['016_filter_aware_search.sql'],[]), 'unexpected migration scope'
    print(db.apply_migrations(conn,db.SQL_DIR))
PY
```

016 only adds functions and does not need an exclusive table rewrite or a maintenance window. The migration can still wait for catalog locks; the deployment command aborts after2s lock waiting. No zero-duration or zero-contention guarantee is made. Existing read statements continue using their existing functions; functions are published together at commit. New code before016 uses the old route. New sessions after016 use the planner.

## Interruption, recovery and rollback

A disconnected non-autocommit migration transaction rolls back. Check `schema_migrations` before repeating PB-005; a committed016 makes retry a no-op. Never run the raw SQL file twice without the migration runner.

For code rollback, retain the deployed commit in `DEPLOYED_REV` and use a detached checkout of the previously recorded `SOURCE_REV`. This changes only the clean code checkout; the deployed branch still points to its approved commit. From the production directory, run:

```sh
DEPLOYED_REV=$(git rev-parse HEAD)
test -z "$(git status --porcelain)" || exit 1
git switch --detach "$SOURCE_REV"
/Users/peter/Agents/agentic-rag/.venv/bin/python -c 'import agentic_rag.search; print(agentic_rag.search.__file__)'
git rev-parse HEAD
```

Verify the printed import belongs to the production checkout and HEAD equals `SOURCE_REV`. Reconnect long-lived MCP processes, run the same original-source reader/writer checks from PB-006, and retain the deployment commit and private evidence. To return to the approved deployed code after resolving the problem, require a clean checkout again and run `git switch --detach "$DEPLOYED_REV"`, verify HEAD/import, and reconnect/recheck clients. Never force reset a dirty checkout. Keep016 in the store: old code uses the unchanged013/015 functions and existing audited writes. No downgrade DDL, data conversion or knowledge loss is required or authorized. Explicit `--context off` or `--strategy hybrid` searches also retain the old candidate behavior for diagnosis; they are per-call controls, not a global deployment rollback.

If the store itself is damaged, preserve evidence and ask the maintainer for restore/cutover authority. Restore the verified015 dump strictly into a separate empty owned target; compare all rows and privileges before any cutover. An in-place `--clean` restore over a running store is unsupported. Recovery to that snapshot loses later legitimate writes unless they are separately recovered through audited gateways;016 code rollback itself loses none.

## Escalation and preserved evidence

The maintainer owns decisions on unsupported source state, failed invariants, live interruption and restore/cutover. Record source/target revisions, migration filenames, private dump hash, strict restore results, affected role and aggregate before/after numbers. Keep raw documents, citations, credentials, query text and dumps in the private directory. Report actionable failures through the existing linked Issue/PR; do not publish sensitive payloads.

## Completion

Completion requires specific deployment approval, committed016, fresh CLI/MCP checks for both privilege levels and protected production inventories, plus a retained verified backup. Passing isolated tests or merging the PR is implementation readiness. It does not establish production adoption.

## Maintenance and sources

The exact branch applies at most4096 eligible nonzero vectors, after a probe capped at4097. Larger sets use an ANN pool of at most4096, with at most2 chunks per document and50 vector-branch outputs. These are distinct budgets. More than4096 closer chunks from one document can still hide another source; broad search remains approximate.

On compatible pgvector the planner uses strict iterative ordering, `hnsw.ef_search=256`, `max_scan_tuples=min(caller,20000)` and `scan_mem_multiplier=min(caller,1)`. The scan count is approximate, not a strict work bound. SQL candidate execution gets at most2s, preserving any tighter nonzero caller timeout. Embedding/reranker network latency has separate existing limits;2s is not an end-to-end search deadline. Savepoints restore settings and preserve caller transactions on success, timeout and cancellation, including planned-function discovery; cancellation propagates to the caller.

Reassess this playbook when supported source/schema, extension capabilities, model dimensions, thresholds, transaction ownership, privileges or measured corpus scale change. Sources: [implementation](../agentic_rag/vector_plan.py), [migration016](../sql/016_filter_aware_search.sql), [pgvector iterative scans](https://github.com/pgvector/pgvector#iterative-index-scans), [PostgreSQL statement timeout](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-STATEMENT-TIMEOUT), [psycopg transaction ownership](https://www.psycopg.org/psycopg3/docs/basic/transactions.html#nested-transactions).
