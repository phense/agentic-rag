# PB-063-UPGRADE: Review and rehearsal evidence

## Scope

- Playbook path and artifact revision/hash: `docs/playbooks/system/rag-063-source-evidence-upgrade.md`,
  uncommitted draft on branch `feat/source-evidence-63` (base `5390a6f`), sha256
  `20b4f39d3418838f3935f7b96bb471c04992b6859f536f05dde6002bd521e7cd`.
- System/interface revision and environment: uncommitted 0.6.16 candidate with
  `sql/029_source_evidence.sql`; owned disposable PostgreSQL 17.10 on 127.0.0.1:55460.
- Owning requirement/task and acceptance criteria: RAG-063 FR-005, US-004, AC-008/009; T063-008/009.
- Required validation level and branches: isolated rehearsal on a populated
  multi-user, multi-domain synthetic copy: upgrade, interrupted migration and
  retry, idempotent rerun, old-client reads and writes, restore-stable versions,
  pre-upgrade restoration and its write-loss limit.
- Owner and readiness deadline: RAG-063 coordinator; before PR handoff.

## Content review

- Reviewer and independence: not yet reviewed. The independent content review
  belongs to the coordinator after implementation.
- Verdict: pending.

## Rehearsal

- Status: run by the implementer on disposable copies (not an independent rehearsal).
- Last validated: 2026-10-31, implementer rehearsal only.
- Validating party: RAG-063 implementation agent.
- Artifact/system revisions and environment: candidate working tree on base
  `5390a6f`; the source store was populated by the archived 0.6.15 code
  (`git archive 5390a6f`); PostgreSQL 17.10, port 55460, scratch in `/dev/shm`.
- Method and applicable execution authority: automated tests on owned
  disposable databases only; no production system, credential or service.
- Command: `env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460
  TMPDIR=/dev/shm/rag63-20261031-tests .venv/bin/python -m pytest
  tests/service/test_evidence_upgrade.py -p no:cacheprovider -q -s` — 2 passed in 30.01 s, exit 0.
- Tested scenarios and branches, with observed results:
  - Populated source: 35 tables, 253 original rows, 16 claims, 28 spans,
    20 sources (4 shared across domains), 77 audit rows, two users' service streams, a pin.
  - U4 interrupted after the migration ran but before commit (simulated crash):
    no `claim_history` table, no 029 marker, database default writable again,
    original hashes unchanged.
  - U4 retry: `migrations_applied == ["029_source_evidence.sql"]`,
    `restore_verified` and `original_rows_unchanged` true, 2.16–2.28 s; original
    table hashes and ACLs verified against the inventory; no revision or history
    rows fabricated.
  - U5 rerun: `migrations_applied == []`, verified backup again.
  - Operator CLI path (U1, U2, plan-only U4, U4, U5, U6) through `rag service --config …`:
    all exit 0; plan wrote no dump; manifest written.
  - U8: `rag evidence show … --json` returns contract version 1; legacy claims
    show revision 1 and empty history; the unmanaged note shows unknown provenance.
  - Old 0.6.15 code after upgrade: identical `get`/search results to before the
    upgrade; its legacy review is recorded as `direct` without an inspected
    version and makes an earlier strict version stale (conflict raised).
  - Restore-stable versions: a verified dump of the upgraded store restored into
    a fresh database yields identical evidence versions for all 15 inspected memories (12 claims, 2 facts, 1 unmanaged note).
  - Pre-upgrade restoration: the U4 dump restored into an empty database matches
    its manifest, has no schema029 objects, serves identical 0.6.15 reads, and
    lacks the post-backup strict review (write-loss limit confirmed).
- Untested branches and environmental limits: remote cutover
  (`prepare-cutover`/`restore-target`) was not rehearsed for this migration;
  a real process kill (instead of a raised exception) and a retained read-only
  fence were not exercised; no production-sized data volume; no live central
  service restart sequence.

## Acceptance and freshness

- Draft status: drafted; no unresolved required fact for the local path.
- Content-review readiness: pending independent review.
- Agreed validation criteria met: implementer rehearsal passed; independent review outstanding.
- Operation/delivery readiness: blocked until the coordinator's independent review.
- Changes since evidence: none.
- Next action and owner: coordinator arranges `playbook-review` and accepts or
  repeats the rehearsal at the final candidate revision.


### Coordinator candidate recheck (2026-10-31)

After adding old-writer source/document concurrency fences and finite legacy-reason
presentation, the coordinator ran the actual browser, populated upgrade and
invalidation fixtures together:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
  TMPDIR=/dev/shm/rag63-20261031-tests PYTHONDONTWRITEBYTECODE=1 \
  LD_LIBRARY_PATH=/home/administrator/Claude/.scratch/agentic-rag-issue59-20261030/browser-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python -m pytest -q tests/browser/test_evidence_browser.py \
  tests/service/test_evidence_upgrade.py tests/test_evidence_invalidation.py \
  -p no:cacheprovider --tb=short
```

Observed: 8 passed, one existing Starlette warning, exit0,71.81s. Both populated
upgrade/operator fixtures passed with the additional lock helper present. The
procedure source hash above is unchanged; coordinator validation is separate
from the still-pending independent content review. No live rollout was attempted.
