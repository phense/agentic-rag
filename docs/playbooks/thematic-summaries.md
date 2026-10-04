# PB-5.7: Thematic profile refresh and016→017 recovery

## Identity and scope

- Class: system operation with development upgrade/recovery rehearsal.
- Origin: RAG-5.7 AC-001–007, [Issue32](https://github.com/phense/agentic-rag/issues/32).
- Audience and owner: local operator; maintainer owns production authorization.
- Target: source `bd01d97`, package0.5.0, schema001–016 to approved Feature7 code/schema017.
- Readiness deadline: reviewed/rehearsed before PR merge; separate authorization before production migration/adoption.
- Last edited:2026-10-04.
- [Review and rehearsal record](../verification/thematic-summaries.md).

## When to use / when not to use

Use this procedure to read or refresh a missing/stale thematic view, or to adopt
the approved additive017 cache on the supported existing installation. Ordinary
search/get remain available throughout. Stop for an unsupported source schema,
unverified backup, unrelated checkout changes, or absent rollout authorization.
Merge permission alone authorizes neither migration nor production adoption.

## Before starting

For reads, supply a theme and the intended project/domain. For upgrade, record
the canonical path, candidate path, exact approved target revision, pre-upgrade
revision/schema and a fresh private backup location. These are operator inputs;
the target merge revision is chosen only after specific PR approval. Use the
canonical `.venv/bin/python` without reinstalling its editable package. Run
candidate commands from the candidate directory with PYTHONPATH selecting it;
running `python -m` from the old canonical root can load old code.

Preflight must find one shared database with the existing roles, all001–016
migrations, intact pins/checkpoints/queue/audit state, and unchanged client
settings/provider configuration. If017 is already recorded, use the retry branch
instead of assuming the migration failed. Keep other migration operators out of
the same installation. A busy worker lock means retry later, never kill a service.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
| --- | --- | --- | --- | --- |
| T1 | Reader, selected evidence | Run `rag summary provider-outages --project /path/to/repository --domain infrastructure`. | JSON status, citations, source versions and warnings;0 provider calls. | Missing017: baseline search/get, U1 only with authorization. Missing/stale cache: T2. |
| T2 | Authorized writer, selected cache | Run the same command with `--refresh`. | Atomic summary_refresh audit, rebuilt/reused counters; current original excerpts. | Failure leaves previous cache intact; inspect error class and retry after correction. T3. |
| T3 | Reader, result | Inspect `invalidated`, `omitted`, provenance, temporal labels and citations. | Exact source substrings; clipped/partial evidence remains explicit. | Use `rag get SLUG --json` for drill-down; narrow topic/domain or increase bounded context. |
| U1 | Maintainer, existing installation | Confirm exact source/target, clean canonical checkout, schema and separate rollout authorization. | Recorded supported source, approved scope and current inventories. | Stop on drift or absent authority. U2. |
| U2 | Operator, private backup | Strictly verify a fresh backup and restore into an owned empty scratch DB. | All public-table row fingerprints and reader/writer/admin grants match one consistent snapshot. | Stop; do not treat maintenance's smoke restore as strict evidence. U3. |
| U3 | Operator, worker/migration | Acquire existing worker lock; apply candidate migration017 transactionally. | Only017 added; original rows/grants retained. | Busy lock: retry later. SQL/interruption: rollback, inspect schema ledger, retry U3. U4. |
| U4 | Operator, canonical code | With clean checkout, adopt the exact approved code while holding the lock; release it afterward. | Deployed revision matches approved target; editable environment/settings retained. | Restore source code if activation/checks fail; keep017/data. U5. |
| U5 | Operator and clients | Verify source/current invariants, writer refresh/read, ordinary search and fresh MCP tools; reconnect selected long-lived clients. |9 reader/15 total tools;6-tool write difference; same original search citations; eligible versioned summaries. | Stop rollout completion and use recovery branch. Existing sessions may continue with loaded old code. |

The strict verifier used in the rehearsal is executable from the candidate root:

```python
from pathlib import Path
from agentic_rag.config import load_config
from scripts.verify_contextual_indexing import verified_backup
report = verified_backup(load_config(), Path('/private/operator-selected/new-backup.dump'))
assert report['strict_restore_exit_zero']
assert report['all_public_table_rows_match']
assert report['application_table_privileges_match']
```

The path is an intentional private operator input and must not already exist.
Keep its report and dump private. `verified_backup` exports a consistent read-only
snapshot, runs pg_dump, then uses `pg_restore --single-transaction --exit-on-error`
into a marker-owned disposable target and compares all rows/grants. It does not
overwrite production or transfer data to a provider.

For U3, the exact migration API exercised by the driver is:

```python
from agentic_rag import db, worker
from agentic_rag.config import load_config
import os
import subprocess
canonical = os.environ['RAG_CANONICAL_PATH']
target = os.environ['RAG_APPROVED_TARGET_REVISION']
if subprocess.check_output(['git','status','--porcelain'], cwd=canonical).strip():
    raise SystemExit('Canonical checkout changed; stop before migration')
lock = worker.acquire_lock()
if lock is None:
    raise SystemExit('Worker lock unavailable; retry without stopping services')
try:
    with db.connect(load_config(), role='owner') as conn:
        done = {r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations')}
        pending = {p.name for p in db.SQL_DIR.glob('*.sql')} - done
        if pending not in (set(), {'017_thematic_summaries.sql'}):
            raise SystemExit('Unsupported pending migration set; stop')
        conn.execute("SET LOCAL lock_timeout='2s'; SET LOCAL statement_timeout='5s'")
        applied = db.apply_migrations(conn, db.SQL_DIR)
        assert applied in ([], ['017_thematic_summaries.sql'])
    subprocess.run(['git','merge','--ff-only',target], cwd=canonical, check=True)
finally:
    lock.close()
```

Use this snippet only after the U1 schema/source check; the migration runner
applies every pending file. Supply `RAG_CANONICAL_PATH` and
`RAG_APPROVED_TARGET_REVISION` as the recorded authorized operator inputs.
U4's activation command fast-forwards the clean canonical checkout to that exact
target. Stop if fast-forward fails; preserve
the checkout and report the exact revision instead of resetting it. No dependency,
re-embedding, client settings edit or database maintenance window is required.
The brief worker lock delays that worker only; other existing clients remain compatible.

## Interruption, recovery and rollback

Migration017 contains a new table/grants only and runs in a transaction. If
interrupted before commit, the table and ledger entry roll back together. If the
commit succeeded but acknowledgement was lost, the ledger makes rerun a no-op.
Verify the schema list before retry; never drop/reset canonical tables. A
successful migration followed by failed code activation is safe for old source
code:017 remains unused until candidate code is adopted.

Refresh holds a per-selection advisory lock; cache and audit commit together.
`commit=False` leaves both under the caller's transaction, including on an idle
connection. Interruption/failure rolls back; a no-change retry preserves generation
time and adds no audit row. Concurrent source changes invalidate the returned
excerpts and remain visible through baseline evidence. Correct the cause and
repeat T2. Reads use rollback-safe savepoints and explicit fallback warnings.

Code rollback retains017 and every original row. After obtaining the required
operational authorization, use the recorded canonical path and source revision
(`RAG_CANONICAL_PATH`, `RAG_SOURCE_REVISION`) in this guarded command. Run it
from the candidate root with the canonical Python so the reviewed worker-lock
helper is selected:

```python
import os
import subprocess
from agentic_rag import worker
canonical = os.environ['RAG_CANONICAL_PATH']
source = os.environ['RAG_SOURCE_REVISION']
def git(*args):
    return subprocess.check_output(['git', *args], cwd=canonical, text=True).strip()
if git('status', '--porcelain'):
    raise SystemExit('Canonical checkout changed; stop without resetting it')
prior_branch = git('branch', '--show-current')
prior_head = git('rev-parse', 'HEAD')
lock = worker.acquire_lock()
if lock is None:
    raise SystemExit('Worker lock unavailable; retry without stopping services')
try:
    subprocess.run(['git', 'switch', '--detach', source], cwd=canonical, check=True)
    assert git('rev-parse', 'HEAD') == source
    print({'prior_branch': prior_branch, 'prior_head': prior_head, 'rollback_head': source})
finally:
    lock.close()
```

This retains the previous branch tip and checks out the source code detached;
keep the printed branch/revision with the incident record. Then change directory
to the canonical root and use its interpreter with `PYTHONPATH="$PWD"` to run
`-m agentic_rag.cli search VERIFY_QUERY --project VERIFY_PROJECT --strategy lexical --json`.
`VERIFY_QUERY` and `VERIFY_PROJECT` are the same recorded pre-upgrade query and
project from U1. Confirm the original citation list, schema017 and intact protected
state; fresh source MCP exposes8 reader/14 total tools. Reconnect affected clients.
The rollback command never changes the database or resets a branch. Stop on any
checkout/check failure and preserve the observed revision. Do not run a down-migration or restore
the whole database to recover a disposable summary. The source/candidate/source
client sequence on a populated017 installation is tested. A full restore is a
separate recovery operation from the verified backup; it can discard writes after
that snapshot and requires explicit recovery authorization.

## Escalation and preserved evidence

Report unsupported schema, repeated gateway/SQL failure, invalid citations or
unexpected scope leakage to the maintainer on Issue32 or a linked defect Issue.
Preserve code/schema revisions, error class, budget, rebuilt/reused/invalidated
counts, strict-verifier result and client tool names. Exclude private excerpts,
source IDs, provider prompts, credentials and dumps from public reports.

## Completion

A read/refresh is complete when the packet and its coverage warnings have been
inspected, citations resolve to eligible originals and no unexpected write/provider
call occurred. Upgrade completion additionally requires preserved-state checks,
approved deployed revision, expected fresh CLI/MCP results and released worker lock.
Issue32 remains open until separately authorized live adoption evidence is recorded.

## Maintenance and sources

Revalidate after changes to source qualification, temporal selection, scope,
cache versioning, schema grants, profile scheduling or budgets. Definitions:
[thematic.py](../../agentic_rag/thematic.py), [migration017](../../sql/017_thematic_summaries.sql),
[reference](../thematic-summaries.md), [spec](../specs/RAG-5.7-thematic-summaries/spec.md).
