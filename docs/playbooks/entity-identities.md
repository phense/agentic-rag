# PB-5.8: Review scoped entity aliases and adopt additive identities

## Identity and scope

- Class: system.
- Origin: RAG-5.8 AC-001–008, [Issue33](https://github.com/phense/agentic-rag/issues/33).
- Audience and owner: authorized operators; maintainer owns rollout/recovery approval.
- Target: source `2a29c50a2fa435d2caeb3354da9dbce92e85e6bb`, schema001–017,
  candidate additive018 on the same PostgreSQL/pgvector store.
- Readiness deadline: before feature handoff; before any separately authorized rollout.
- Last edited:2026-10-04.
- [Review and rehearsal evidence](../verification/entity-identities.md).

## When to use / when not to use

Use this procedure to inspect/confirm/revoke an alias or to adopt018 on the supported
existing installation. Keep the original source attestation and project/domain
selector available. Stop for unsupported schema/code, a missing verified backup,
conflicting anchors, unclear source support or absent operational authorization.
A PR merge approval does not authorize production migration, activation or interruption.

## Before starting

For reads choose the exact name, domain and project or explicit global scope. For
review identify both names, the relation evidence UUID and its original namespace,
source ID, source_at and quote in `claim_sources` through `rag get UUID --json`. Unknown applicability needs an
explicit separate source correction, never a guessed alias. The shared reader roles
have no new per-user ACL; project/domain controls entity selection.

For rollout record `RAG_CANONICAL_PATH`, `RAG_CANDIDATE_PATH`,
`RAG_APPROVED_TARGET_REVISION`, `RAG_SOURCE_REVISION` and a new private
`RAG_BACKUP_DUMP` path. These are intentional operator inputs, not filled deployment
approval. The source revision above must match a clean canonical checkout. Verify
all001–017 migration filenames, existing role/grant matrix, original pins, sources,
checkpoint/queue/audit IDs and provider/client config fingerprints. Record normal
concurrent-source additions against a consistent backup snapshot, not stale counts.

Use the canonical `.venv/bin/python` from the candidate directory with
`PYTHONPATH="$RAG_CANDIDATE_PATH"`; do not reinstall its editable package or edit
client settings. Ordinary source queries and old/new writes remain compatible.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
| --- | --- | --- | --- | --- |
| A1 | Reader, selected entity | `rag entity resolve NAME --domain DOMAIN --project PROJECT` | Original citations, current facts, relation/suggestion warnings;0 provider calls | Missing018: ordinary exact search/get; U1 only with rollout approval |
| A2 | Operator, original source | Inspect actual namespace/source ID/quote and both entity meanings | Complete active user span and known same scope/domain | Uncertain: retain review suggestion; never confirm from embedding similarity |
| A3 | Writer, relation | Save an untimed/manual CLI attestation or reuse the exact timed source with `memory_entity_alias` below; confirm only after A2 | Immutable original evidence document; review or accepted state and reason | Competing anchor/chain: A4; unsupported span remains review-only |
| A4 | Writer, mistaken relation | `rag entity review UUID --state revoked --reason 'Mistaken link'` | Audited revocation; original history retained; names separate | Inspect failure and UUID, preserve evidence; do not delete facts |
| A5 | Reader, original facts | Repeat A1; use `--history` or an explicit `--as-of` for temporal checks | Trust-qualified originals, explicit expired/superseded/conflict labels | Ambiguity/limits: narrow attribute; inspect originals and repair source/link |
| U1 | Maintainer, source and target | Verify supported source, clean checkout and separate exact rollout authorization | Recorded source/target/schema/config and authorized scope | Stop on drift or absent authority |
| U2 | Operator, private backup | Strictly verify a fresh dump with the helper below | Full consistent table fingerprints and prior application grants restore into an owned empty DB | Stop on any discrepancy; preserve private report |
| U3 | Operator, migration | Acquire existing worker lock and apply only018 using the guarded code below |018 ledger/table/grants atomically added; original rows unchanged | Busy lock: retry later; no service kill. SQL failure: rollback and inspect ledger |
| U4 | Writer, explicit index | Repeat one bounded `rag entity backfill --limit 100` under the existing lock | Mapped/remaining/unresolved counts; committed completed batches retained | Failure: correct cause and repeat; no cursor/reset; unknowns stay unresolved |
| U5 | Operator, canonical code | Fast-forward to the exact approved target while holding the worker lock | Checked deployed revision; unchanged environment/config/jobs | Activation failure: retain018 and use source code recovery; never reset knowledge |
| U6 | Readers and writers, clients | Repeat original ordinary query, entity query, fresh CLI/MCP and no-op backfill |10 reader/18 total tools; original citations/pins/checkpoints/audits retained | Stop completion and use recovery; reconnect selected long-lived clients only |

A3's public synthetic example demonstrates syntax; use actual source inputs for a
real relation:

```bash
rag entity alias --alias orion-old --target orion --domain infrastructure \
  --project /absolute/repository --namespace actual-session \
  --source-id actual-event --quote 'orion-old is another name for orion.' \
  --effective-at 2026-02-01T00:00:00Z --complete
rag entity review RELATION_UUID --state accepted --reason 'Checked original meaning and source'
```

The CLI does not accept a source timestamp. Use it for a new manual attestation
or a registered source whose `source_at` is null. For a dated registered source,
copy its exact original `claim_sources` metadata into the main-session
`memory_entity_alias` evidence dict, with `source_at` mapped to `timestamp`:

```json
{
  "alias": "orion-old", "target": "orion", "domain": "infrastructure",
  "project": "/absolute/repository", "effective_at": "2026-02-01T00:00:00Z",
  "confirm": false,
  "evidence": {
    "namespace": "actual-session", "source_id": "actual-event", "role": "user",
    "timestamp": "2026-02-01T00:00:00Z",
    "quote": "orion-old is another name for orion.", "complete": true
  }
}
```

These controlled values illustrate the contract; substitute only the inspected
original fields. A different timestamp/role for a registered source is rejected.
Never invent a new namespace/source ID to evade the mismatch.

The first command keeps a review suggestion. `--confirm` is an explicit alternative
to the second command after A2. A complete quote or a user role alone never implies
semantic confirmation. New unreviewed support cannot inherit the bound confirmation.

The strict U2 helper has been exercised on the supported source and target. Supply
an unused private path; retain the dump/report locally with restrictive permissions:

```python
import json, os
from pathlib import Path
from agentic_rag.config import load_config
from scripts.verify_contextual_indexing import verified_backup
p=Path(os.environ['RAG_BACKUP_DUMP'])
report=verified_backup(load_config(),p)
with p.with_suffix('.report.json').open('x') as f:
    json.dump(report,f,indent=2)
p.with_suffix('.report.json').chmod(0o600)
assert report['strict_restore_exit_zero'] and report['all_public_table_rows_match']
assert report['application_table_privileges_match']
```

U3–U5 use the existing worker lock. This code rejects unrelated pending migrations,
limits migration lock waits and retains every successful backfill batch. A retry
may begin with018 already present. The approved target is an operator input chosen
only after explicit approval, never an inferred branch head:

```python
import os, subprocess
from pathlib import Path
from agentic_rag import db, store, worker
from agentic_rag.config import load_config
canonical=os.environ['RAG_CANONICAL_PATH']
target=os.environ['RAG_APPROVED_TARGET_REVISION']
source=os.environ['RAG_SOURCE_REVISION']
candidate=Path(os.environ['RAG_CANDIDATE_PATH']).resolve()
def git(*args):
    return subprocess.check_output(['git',*args],cwd=canonical,text=True).strip()
def check_code():
    if source!='2a29c50a2fa435d2caeb3354da9dbce92e85e6bb':
        raise SystemExit('Unsupported source revision')
    if git('rev-parse',target+'^{commit}')!=target:
        raise SystemExit('Target must be an exact approved commit')
    if git('status','--porcelain') or git('rev-parse','HEAD')!=source:
        raise SystemExit('Source checkout drift; stop without resetting it')
    if subprocess.check_output(['git','status','--porcelain'],cwd=candidate,text=True).strip():
        raise SystemExit('Candidate checkout drift')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=candidate,text=True).strip()!=target:
        raise SystemExit('Candidate is not the approved target')
    if any(Path(m.__file__).resolve().parents[1]!=candidate for m in (db,store,worker)):
        raise SystemExit('Imported modules are not from the approved candidate')
    if db.SQL_DIR.resolve()!=candidate/'sql':
        raise SystemExit('Migration path is not the approved candidate')
    subprocess.run(['git','merge-base','--is-ancestor',source,target],cwd=canonical,check=True)
check_code()
lock=worker.acquire_lock()
if lock is None:
    raise SystemExit('Worker lock busy; retry without stopping services')
try:
    check_code()
    cfg=load_config()
    with db.connect(cfg,role='owner') as c:
        done={r['filename'] for r in c.execute('SELECT filename FROM schema_migrations')}
        source_files={p.name for p in db.SQL_DIR.glob('*.sql') if p.name<'018'}
        if done not in (source_files,source_files|{'018_entity_identities.sql'}):
            raise SystemExit('Unsupported source schema; stop')
        pending={p.name for p in db.SQL_DIR.glob('*.sql')}-done
        if pending not in (set(),{'018_entity_identities.sql'}):
            raise SystemExit('Unexpected pending migration; stop')
        c.execute("SET LOCAL lock_timeout='2s'; SET LOCAL statement_timeout='5s'")
        assert db.apply_migrations(c,db.SQL_DIR) in ([],['018_entity_identities.sql'])
    with db.connect(cfg,role='writer') as c:
        while True:
            c.execute("SET LOCAL lock_timeout='2s'; SET LOCAL statement_timeout='5s'")
            result=store.backfill_entity_identities(c,limit=100)
            print(result)
            if result['remaining']==0:break
    check_code()
    subprocess.run(['git','merge','--ff-only',target],cwd=canonical,check=True)
    assert git('rev-parse','HEAD')==target
finally:
    lock.close()
```

After U5 switch the working directory to the canonical checkout and use its
interpreter with `PYTHONPATH="$RAG_CANONICAL_PATH"` for U6. Source code remains
unchanged throughout U3/U4; candidate code runs only against the same selected
configuration. No provider/dependency/model/client settings change is required.

## Interruption, recovery and rollback

018's DDL and ledger entry share the migration transaction. Interruption before
commit rolls both back. If commit succeeded but acknowledgement was lost, rerun
finds018 and applies nothing. Preserve the schema inventory; never drop original
tables or down-migrate. With the worker lock released, old clients can continue
using their original exact-key contracts.

Backfill commits one batch at a time. A failed/caller-rolled-back batch retains no
partial identity, attachment or audit; retry scans remaining/stale mappings without
a UUID cursor. Completed batches survive. A no-change retry writes no audit. New
old/new-client assertions remain readable with deterministic IDs even before a
later backfill. Unknown applicability remains counted and unlinked. Concurrent
backfills serialize separately; no locks are added to existing mining transactions.

Alias/source/review effects share their gateway transaction. Failure before commit
leaves original relations intact. Unchanged accepted alias retries reuse their
record. Explicit revocation retains original facts/sources/audit; a later accepted
review rechecks the same bound source span and star constraints. Administrator purge
keeps its existing confirmed deletion semantics; ordinary alias repair uses revocation.

If code activation or U6 fails, retain018 and completed mappings. With separately
authorized operational recovery, a clean canonical checkout and the recorded
source revision, acquire the existing worker lock and run:

```python
import os, subprocess
from agentic_rag import worker
canonical=os.environ['RAG_CANONICAL_PATH']
source=os.environ['RAG_SOURCE_REVISION']
target=os.environ['RAG_APPROVED_TARGET_REVISION']
def git(*args):
    return subprocess.check_output(['git',*args],cwd=canonical,text=True).strip()
def check_code():
    if source!='2a29c50a2fa435d2caeb3354da9dbce92e85e6bb':
        raise SystemExit('Unsupported recovery source revision')
    if git('rev-parse',target+'^{commit}')!=target:
        raise SystemExit('Recovery target must be an exact approved commit')
    if git('status','--porcelain') or git('rev-parse','HEAD') not in (source,target):
        raise SystemExit('Recovery checkout drift; stop without resetting it')
check_code()
previous=dict(branch=git('branch','--show-current'),revision=git('rev-parse','HEAD'))
lock=worker.acquire_lock()
if lock is None:
    raise SystemExit('Worker lock busy; retry without stopping services')
try:
    check_code()
    subprocess.run(['git','switch','--detach',source],cwd=canonical,check=True)
    assert git('rev-parse','HEAD')==source
    print(previous)
finally:
    lock.close()
```

The recovery code records the previous branch and revision before switching. Then run the original ordinary query with source code
and verify its citations and protected state. Fresh source MCP is9/15. The existing
branch tip is retained; no reset or database mutation is involved. Full restore is
a separate recovery authorization and may discard writes since the backup snapshot.

## Escalation and preserved evidence

Report unsupported schema, repeated gateway failure, invalid original citations,
foreign scope/domain output or unresolvable conflicts on Issue33. Preserve source/
target revisions, hashes, schema ledger, error class, review state, bounded counters,
private backup verification and original table/role/config fingerprints. Public
reports contain aggregates and controlled fixtures; exclude real bodies, identifiers,
credentials, prompts and dump paths. No new provider transfer is authorized.

## Completion

Alias review completes when eligible original citations and the intended relation
state are verified, and a revoked link separates the names. Upgrade additionally
requires original state/grants retained, remaining known mappings0 at the checked
snapshot, unresolved unknowns disclosed, expected fresh clients and released worker
lock. Keep Issue33 open until separately authorized merge/adoption acceptance.

## Maintenance and sources

Revalidate after changes to identity normalization, source trust, domain repair,
valid-time selection, transaction ownership, schema grants or client tools.
[entities.py](../../agentic_rag/entities.py), [migration018](../../sql/018_entity_identities.sql),
[reference](../entity-identities.md), [spec](../specs/RAG-5.8-entity-identities/spec.md),
[driver](../../scripts/verify_entity_identities.py).
