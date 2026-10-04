# PB-5.10: Evaluate confirmed failures and recover offline evaluation

## Identity and scope

Class: system. Owner: maintainer. Audience: local operators and reviewers.
Origin: RAG-5.10 AC-001–008, [Issue35](https://github.com/phense/agentic-rag/issues/35).
Source: reviewed Feature9d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d/schema019;
live1294d6c44fd02b66715692f12791bfa2fd4c8856/schema018.
Target: exact separately approved Feature10 commit, unchanged018/019 schema support.
Last edited:2026-10-04. Required reviewed/rehearsed evidence before handoff:
[verification](../verification/failure-evaluation.md).

## When to use / when not to use

Use for a bounded offline evaluation, private confirmed-correction labels, or separately
authorized code adoption/recovery. Stop if corpora mix private/public formats, original
labels lack confirmed user support, split/source identity leaks, model identity drifts,
paths are public/symlinked/occupied, or candidate/source revisions are unknown. Candidate
files never authorize production configuration or prompt changes. Merge approval does
not authorize deployment, migration or service interruption.

## Preconditions

Use the existing canonical interpreter/configuration and explicit candidate PYTHONPATH.
Keep private labels/backups outside all Git worktrees, with0700 directories and0600 files.
Choose new output paths; retain failed partial reports for diagnosis. Record exact source
and target revisions, schema, model identity and budgets. Do not change client settings,
install another provider or editable-reinstall the package. Read-only credentials apply
to correction export/evaluation and Trading controls.

## Decisions and actions

| Step | Actor/artifact | Action | Confirmation | Failure path |
| --- | --- | --- | --- | --- |
| E1 | Operator/public corpus | Validate whole-family split and source labels; run optimize | Sealed dev candidate precedes held-out results; every miss/index failure visible | Fix dev corpus and use a new output path; do not tune held-out labels |
| E2 | Operator/private corrections | Export one exact boundary; evaluate local private file | Original reviewed user support/hashes,0600 and zero network/writes | Zero eligible cases is valid; withhold unsafe/changed truth |
| E3 | Operator/public mining | Explicitly run configured native stage | Actual calls, independent labels, unsafe-output count and replay checks recorded | Keep provider failures as misses; no substitute-provider retry |
| E4 | Reviewer/candidate | Inspect raw numerators, source hashes, uncertainty, cost and limits | Candidate survives independent complete review; no live loader | Reject unsupported gains or arbitrary candidate/profile fields |
| U1 | Maintainer/current018 | Separately authorize exact combined target; use PB-5.9 | Strict fresh018 backup/restore and guarded019 activation/retry pass | Busy worker/drift: stop and retry safely; no kill/reset |
| U2 | Maintainer/current019 | Separately authorize code-only target; verify strict019 backup and clean exact source/target | Original rows/grants and fresh old/new CLI/MCP contracts retained | Inspect dirty/unsupported source before any switch |
| R1 | Operator/failed evaluation | Retain partial directory; rerun on a new path with frozen dev source | Independent complete result; old candidate unchanged | Never overwrite a sealed candidate or rerun held-out tuning |
| R2 | Operator/authorized code recovery | Recover source code with detached checkout; retain019 and branch refs | Existing get/search and10-reader/18-main MCP tools still work | Database restore is separate authority and would lose later writes |

## Execute bounded evaluation

1. Run from the candidate checkout with `PYTHONPATH=.` and the original interpreter.
2. Choose a new public output directory and run the command below.
3. Inspect candidate.json, separate dev/held-out reports, raw failures and context budgets.

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m agentic_rag.cli \
  benchmark optimize --output /absolute/new/public-evaluation --repeats 20
```

For actual mining effects, run the explicit public stage first; then provide its development
candidate to a new optimize run. Its held-out results remain a separate file.

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m agentic_rag.cli \
  benchmark optimize-mining --mine-model --output /absolute/new/public-mining
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m agentic_rag.cli \
  benchmark optimize --mining-candidate /absolute/new/public-mining/candidate.json \
  --output /absolute/new/public-evaluation --repeats 20
```

## Execute private local evaluation

1. Create a private0700 parent outside Git and select the exact domain/project.
2. Export to a new private0600 file using the command below.
3. Evaluate the original file locally to another new private output; inspect aggregate counts.

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m agentic_rag.cli \
  benchmark export-corrections --domain infrastructure --project /exact/project \
  --output /absolute/private/new-labels.json
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m agentic_rag.cli \
  benchmark evaluate-corrections --input /absolute/private/new-labels.json \
  --output /absolute/private/new-results.json
```

Use `--scope global` without a project only when that boundary is intended. Never copy
private labels into the public synthetic corpus or supply them to native provider commands.

## Execute separately authorized source019 code-only adoption

The current source019 tree must match the reviewed Feature9 tree (a merge commit with
that identical tree is supported), and the exact approved target must be available in
both clean separate checkouts. Preserve the existing interpreter/config environment.
Set `RAG_CANONICAL_PATH`, `RAG_CANDIDATE_PATH`, `RAG_APPROVED_TARGET_REVISION`,
`RAG_ORIGINAL_PYTHON`, `RAG_BACKUP_DUMP` and `RAG_BACKUP_REPORT` to approved inputs.
Keep backup paths new and private. Create the strict verified019 backup/report first:

```python
from pathlib import Path
import json, os
from datetime import datetime, timezone
from agentic_rag.config import load_config
from agentic_rag import db
from scripts.verify_contextual_indexing import verified_backup
from scripts.activate_failure_evaluation import source_identity
cfg = load_config()
dump = Path(os.environ['RAG_BACKUP_DUMP'])
report_path = Path(os.environ['RAG_BACKUP_REPORT'])
report = verified_backup(cfg, dump)
report['source_db_name'] = cfg.db_name
with db.connect(cfg, role='owner') as conn:
    report['source_identity'] = source_identity(conn)
report['verified_at'] = datetime.now(timezone.utc).isoformat()
fd = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(report, stream, indent=2)
```

Run the same guarded helper exercised by the owned rehearsal:

```bash
PYTHONPATH="$RAG_CANDIDATE_PATH" "$RAG_ORIGINAL_PYTHON" \
  "$RAG_CANDIDATE_PATH/scripts/activate_failure_evaluation.py" \
  --canonical "$RAG_CANONICAL_PATH" --candidate "$RAG_CANDIDATE_PATH" \
  --approved-target "$RAG_APPROVED_TARGET_REVISION" \
  --verified-dump "$RAG_BACKUP_DUMP" --backup-report "$RAG_BACKUP_REPORT"
```

It requires exact unchanged019 SQL/ledger, strict fresh019 backup checksum/0600 flags
and actual server/database identity. It checks both clean checkouts before and under
the worker lock, immediately after schema verification/before Git and after switching.
It never applies DDL. A busy lock or drift causes rejection; correct the cause and retry.
Already-active exact targets are idempotent. Fresh clients must reconnect to load code.
For separately authorized recovery, use the same helper with `--recover`; it skips backup
restoration and detaches source code while retaining019, later writes and branch refs:

```bash
PYTHONPATH="$RAG_CANDIDATE_PATH" "$RAG_ORIGINAL_PYTHON" \
  "$RAG_CANDIDATE_PATH/scripts/activate_failure_evaluation.py" \
  --canonical "$RAG_CANONICAL_PATH" --candidate "$RAG_CANDIDATE_PATH" \
  --approved-target "$RAG_APPROVED_TARGET_REVISION" --recover
```

## Rehearsal and code recovery

The unified driver executes actual owned Git source019→target019 fast-forward, repeat,
detached source019 recovery, unchanged branch refs, strict019 backup/restore, old/new
clients and simultaneous uncommitted writers. It rejects dirty source, busy worker lock
and drift between schema verification and Git switch. Before/under the lock/immediately
before switching it checks exact clean source/candidate; afterward it verifies the target.
These operations add no migration and retain original database rows/grants.

The same driver executes the actual guarded PB-5.9 combined018→019 activation/retry/source018
code recovery on populated owned copies, including eight rejection paths. Source018 code
continues to work on retained019. It also strictly restores a fresh private production018
snapshot and rehearses interrupted019 DDL/retry there. Trading is read-only.

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_failure_evaluation.py \
  --output /absolute/new/public-evidence --private-dir /absolute/private/new-directory \
  --repeats 20 --mine-model --production-copy --trading
```

No production activation is performed by this rehearsal. For the supported current live018
installation, the executable authorized upgrade/recovery command is [PB-5.9](incremental-ingestion.md),
with the exact separately approved combined target. Already019 code-only deployment uses the exact guarded command above; retain the strict019 backup and exact adopted/recovered revisions as operator evidence.
A full database restore is not implemented by Feature10 and needs separate loss-boundary approval.

## Executed evidence and recovery limits

PB-5.10 is reviewed and rehearsed at measured code5b390692e32e07c8816e98091dfa66e15e0c2cb3.
The unified driver exits0 and uses the same guarded019 operator helper for actual owned
activation/retry/detached recovery. It executes dirty/busy/schema-time drift rejection,
strict backup/restore, original rows/grants, overlapping old/new writers, branch retention
and worker lock reacquisition. Combined018→019 also executes PB-5.9's eight rejection
cases and schema interruption/retry/no-op. A fresh populated production018 copy preserves
all21 source tables/grants after restore and migration on the copy; canonical writes0.
See [raw evidence](../benchmarks/2026-10-04-failure-evaluation/results.json) and
[verification](../verification/failure-evaluation.md) for exact counts/commands/reviews.

Recovery retains019 and later writes; it restores code, not the database. Restoring an
older dump would discard later rows and requires separate approval. A failed evaluation
keeps its partial directory/candidate; never overwrite it or tune held-out labels. No
operator action above is permission to change production. Fresh sessions must reconnect
to discover new CLI behavior; existing MCP tools/privileges/configuration remain unchanged.
