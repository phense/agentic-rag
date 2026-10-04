# PB-5.9: Adopt incremental embedding reuse or recover source code

## Identity and scope

- Class: system.
- Origin: RAG-5.9 AC-001–008, [Issue34](https://github.com/phense/agentic-rag/issues/34).
- Owner: maintainer; audience: authorized local operators.
- Supported source:1294d6c44fd02b66715692f12791bfa2fd4c8856, schema001–018.
- Target: the exact separately approved Feature9 commit, additive019, existing store.
- Readiness deadline: before handoff and before separately authorized production adoption.
- Approved local combined target adopted on2026-10-04: `b849d3423a51a5d0f90273c3d5ed88433ec78778`/schema019. [Production acceptance](../verification/features9-10-production-adoption.md).
- Last edited:2026-10-04. [Review/rehearsal evidence](../verification/incremental-ingestion.md).

## When to use / when not to use

Use this procedure for explicit local adoption or code recovery on the supported
installation. Merge approval alone does not authorize migration, activation or service
interruption. Stop for absent operational authority, dirty/unsupported source, missing
strictly verified backup or busy worker lock. No service termination is part of this procedure.

## Before starting

Record clean canonical/candidate paths and an exact40-character approved target.
Keep the existing interpreter/environment and a private new backup/report path.
Inventory source schema, roles/grants, pins, domains, sources, queued/accepted work,
checkpoints and audit history. Preserve config, hooks, job schedules and both MCP
privilege levels. Existing sessions may continue using source code while019 is added;
reconnect selected MCP clients after activation to load candidate code. The singleton
worker lock prevents an old worker crossing activation; an already running worker
causes immediate rejection. Operator/session writes remain audited.

## Decisions and actions

| Step | Actor and artifact | Action | Check | Failure path |
| --- | --- | --- | --- | --- |
| U1 | Maintainer, exact target | Confirm merge and separate local rollout authority | Approved source/target/scope recorded | Stop without authority |
| U2 | Operator, private backup | Execute consistent018 backup and strict owned restore below | Every public table/row and application grant matches;0600 checksum/report | Stop; retain diagnostic report, never restore over production |
| U3 | Operator, candidate | Run guarded activation below with original interpreter | Exact clean checkouts/modules, worker lock,018→019 atomic migration, target HEAD | Busy/drift: correct cause and retry; no kill/reset |
| U4 | Readers/writer, clients | Repeat original get/search, fresh10/18-tool MCP and a separately authorized controlled save | Original citations/eligibility preserved; unchanged inputs avoid inference with known model | Investigate or use R1; never infer a quality gain from cache speed |
| U5 | Operator, inventories | Compare original evidence/pins/domain/config/checkpoint/queue/audit retention, allowing normal audited additions | No state loss; required suites and recorded checks pass | Keep acceptance open and recover code if needed |
| R1 | Operator, approved target | Run guarded `--recover` below | Source code active;019 and all later knowledge retained | Dirty/unexpected source/schema: inspect and stop |
| R2 | Maintainer, restore request | Separately authorize any full restore with accepted loss boundary | Exact backup point, later-write loss and owned strict restore proof recorded | No production restore is implemented or implied here |

## Executable backup and adoption

Set operator inputs for canonical/candidate paths, approved target and new private
backup paths. These values are placeholders for approved inputs, not authorization.
Run from the clean candidate with its `PYTHONPATH` and the canonical installation's
original interpreter/config environment. Do not editable-reinstall packages.

```python
from pathlib import Path
import json, os
from agentic_rag.config import load_config
from scripts.verify_contextual_indexing import verified_backup
from scripts.activate_incremental_ingestion import source_identity
from agentic_rag import db
from datetime import datetime, timezone
cfg = load_config()
dump = Path(os.environ['RAG_BACKUP_DUMP'])
report_path = Path(os.environ['RAG_BACKUP_REPORT'])
if report_path.exists(): raise SystemExit('Choose a new backup report path')
report = verified_backup(cfg, dump)
report['source_db_name'] = cfg.db_name
with db.connect(cfg, role='owner') as conn:
    report['source_identity'] = source_identity(conn)
report['verified_at'] = datetime.now(timezone.utc).isoformat()
fd = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(report, stream, indent=2)
```

```bash
PYTHONPATH="$RAG_CANDIDATE_PATH" "$RAG_ORIGINAL_PYTHON" \
  "$RAG_CANDIDATE_PATH/scripts/activate_incremental_ingestion.py" \
  --canonical "$RAG_CANONICAL_PATH" --candidate "$RAG_CANDIDATE_PATH" \
  --approved-target "$RAG_APPROVED_TARGET_REVISION" \
  --verified-dump "$RAG_BACKUP_DUMP" --backup-report "$RAG_BACKUP_REPORT"
```

The guarded implementation refuses unsupported schema/code, abbreviated target,
source/candidate drift, wrong imported module/migration path, invalid backup checksum,
permissions, actual cluster/database/connection identity or a busy worker lock. The
verified backup must be dated within one hour. It repeats checkout/backup guards
under the lock and checkout guards immediately before Git activation/recovery.
Migration commits before code activation. An interruption before DDL
commit rolls back019; after commit, retry applies no migration and completes activation.
No cache backfill is necessary. Old vectors cannot silently become reusable cache entries.

## Code recovery and verification

```bash
PYTHONPATH="$RAG_CANDIDATE_PATH" "$RAG_ORIGINAL_PYTHON" \
  "$RAG_CANDIDATE_PATH/scripts/activate_incremental_ingestion.py" \
  --canonical "$RAG_CANONICAL_PATH" --candidate "$RAG_CANDIDATE_PATH" \
  --approved-target "$RAG_APPROVED_TARGET_REVISION" --recover
```

Recovery checks the same exact target/clean source/imported-module guards and worker
lock, then detaches the canonical checkout at source1294d6c. It retains019, original
knowledge and later audited writes; the prior branch reference is preserved. Verify
fresh source CLI/MCP get/search and queued mining/reembedding. No database downgrade
or service stop is required. Full restore is a separate procedure and can discard later
writes. Derived cache entries are disposable, but no cache deletion command is needed.

## Rehearsal and remaining limits

`scripts/verify_incremental_ingestion.py` exercises this actual guarded implementation
on an owned Git clone/populated018 database, including busy-lock/drift rejection,
DDL rollback, committed-schema retry, source code recovery and fresh source/new/source
CLI/MCP. It also kills/restarts real mining processes before and after application
commit, strictly restores source/target dumps and can rehearse a private production
snapshot on an owned copy. All production access in that driver is read-only.

Record executed commands/results/source revisions in the linked verification record.
A drafted procedure or a successful fresh install does not satisfy this playbook.
