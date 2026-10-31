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

- Reviewer and independence: independent final reviewer, complete candidate
  `96edf09` (51/51 file hashes verified); did not implement this feature.
- Verdict on that candidate: Changes required (PB063-R1). The restore branch
  lacked executable manifest verification, the client configuration switch and
  the required 0.6.15 service runtime for schema028. Corrections below await
  independent re-review. The original playbook hash above describes that reviewed
  candidate, not the corrected procedure.

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


### Coordinator recovery correction (2026-10-31)

The revised R1–R4 branch uses only the public operator inventory output for its
manifest comparison. It verifies the U4 dump digest before restore and compares
all original table hashes/counts, grants, object owners, sequence positions,
migration filenames/timestamps, login owner, collation and vector version.
The old database is retained; writers stay stopped until every launch points to
the recovery database with the retained 0.6.15 runtime. The 0.6.16 operator is used
only for read-only inventory of schema028.

- Corrected playbook SHA-256: `4d45513fbeb2b2fcd5175d67d99d0a4e9a74cf48619ce73e720099b4c6af8d95`.
- Rehearsal: `tests/service/test_evidence_upgrade.py`, using the command above
  restricted to that file, `-q -s -p no:cacheprovider --tb=short`.
- Actual result: 2 passed, exit0,30.51s. Both tests use owned disposable databases;
  the schema028 fixture was populated by archived0.6.15 at `5390a6f`.
- Representative original state:35tables,253rows,16claims,28spans,20sources,
  77audit rows and4cross-domain shared sources. Original data/grants and interrupted
  retry pass; upgrade rerun applies no migration.
- The recovery test extracts and executes both Python snippets from the
  corrected playbook, then runs the public inventory CLI. Changed grants,
  table hashes, owners and sequences each reject cutover. This replaces the
  previous reliance on the private `upgrade._verify` method as recovery proof.
- The configuration copy preserves all settings and changes only `db.name`.
  With that launch configuration, archived0.6.15 CLI `service status` reports
  `service_ready: true`; `get` and an authenticated scoped0.6.15 REST read return
  the original memory. The0.6.16 service gate rejects that restored028 database.
- PB063-R2/R3/R4 guidance is corrected: the compatibility source-version label
  is explained; baseline revision1 applies only to untouched legacy records;
  applicability is limited to the rehearsed0.6.15/schema028 source.
- Limits: subprocess launch/configuration switching and an in-process authenticated
  API request were exercised. No systemd restart, live TLS endpoint, remote-host
  restoration, worker/timer resumption, production volume or production cutover
  was executed. Those deployment-specific U3 commands remain operator inputs.
- Two initial runs exposed recovery-fixture setup errors (policy permissions and
  REST result envelope); both were corrected before the successful full-file run.
- Content review status of this revised procedure: pending fresh independent
  review. No production readiness or rollout authorization is implied.

Focused writing self-check: Small correction to an existing procedure. Commands
were checked against the public CLI and executed above; placeholders are declared
operator inputs, outcomes and failure stops are explicit, and original numerical
facts remain unchanged.
