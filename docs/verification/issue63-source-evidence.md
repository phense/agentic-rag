---
id: V-063
title: Source evidence verification
type: reference
doc_id: issue63-source-evidence-verification
readers: [maintainer]
status: drafted
version: 0.6.16
depends_on: []
assets: []
last_reviewed: 2026-10-31
summary: Measured source-evidence behavior, populated upgrade and recovery checks, review findings and delivery limits for Issue63.
---

# Source evidence verification

[Issue63](https://github.com/phense/agentic-rag/issues/63) adds one bounded evidence
contract to local and central CLI, MCP, REST and dashboard clients. The source is
0.6.15/schema028 at `5390a6f6b4a7cce4b27abc9b51226acf2dac6223`; the corrected
implementation is `08a75f5d4b832906d72908f5709c694e232476c5`, targeting0.6.16/schema029.
Independent re-review accepts the corrected code and procedure; the final
whole-suite run remains a delivery gate at this report's draft revision. No production migration or cutover was performed.

Terms: an evidence span is one exact stored quotation; a source event can contain
several spans. An attestation is an operator's manual assertion. Review records
an operator decision, not independent verification. Eligibility is the existing
SQL decision about whether a memory can support a current result. A version
binds a decision to the complete inspected evidence, including later-page spans.
The manifest records original table hashes/counts and permissions for restoration.

## Measured practical examples

The [measurement script](../benchmarks/2026-10-31-source-evidence/measure.py) ran
against the archived source and the clean corrected implementation above. The
[JSON results](../benchmarks/2026-10-31-source-evidence/results.json) record both
revisions and `candidate_tree_dirty: false`.

| Synthetic case | Before | After | Meaning and limit |
|---|---:|---:|---|
|40 decisions after withdrawal/reinstatement changed inspected evidence |40 committed |0 committed;40 conflicts;0 rejection rows written | New callers supply the inspected version; legacy no-token calls remain supported |
|48 stored spans inspected |48 spans in one legacy response,33,984bytes |20 in the first contract response,22,547bytes; all48 in3pages | New source navigation contains0 host namespace locators versus48 in the legacy response; legacy `get` metadata remains compatible |
|5 historical facts with a newer replacement in another domain |5 falsely labeled superseded |0 falsely labeled superseded | Existing domain-isolated SQL eligibility remains authoritative |

These are structure and correctness counts on disposable PostgreSQL17 databases.
They do not measure model accuracy, production latency, network behavior or
production corpus coverage. Reproduce from the repository root with an owned
PostgreSQL17 test cluster, its configured login, a separate scratch directory and
the installed checkout package:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE \
  PGPORT=<owned-test-port> TMPDIR=<owned-scratch-directory> \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  docs/benchmarks/2026-10-31-source-evidence/measure.py
```

## Verification evidence

| Check | Actual result | Scope |
|---|---|---|
| Manual-attestation regression before correction |5failed,26deselected,1existing warning,exit1,39.33s | Local and REST aggregation falsely reported complete user support |
| Full affected contract/transport files after correction |31passed,1existing warning,exit0,21.22s | Local operator/manual/service namespaces, mixed sources, repeated spans, partial events, withdrawal and reviewed support |
| Populated upgrade and public recovery fixtures |2passed,exit0,30.51s |35original tables/253rows,16claims,28spans,20sources,77audit rows;4sources shared across domains |
| Independent architecture probes rerun after correction |All5units passed,exit0 | Success26/26; audit rollback/retry10/10; old-writer race3/3; manual attestation4/4; old service gate on029,1/1 |
| Dashboard browser/upgrade/invalidation selection before the review correction |8passed,1existing warning,exit0,71.81s | Real Chromium pagination and decisions; migration and current-read invalidation; final full suite must cover the corrected tree |
| Wheel build and archive inspection |`uv build --wheel` exit0;179entries inspected | Package0.6.16; migration029, evidence producer and dashboard assets match the source; native prompt assets present |
| Independent correction edge probe |26/26checks,exit0 | Namespace boundaries, partial/refuted/removed/inferred manual support, mixed sources, unchanged canonical eligibility; separate owned database |
| Final whole-suite run |Pending on the corrected frozen candidate | Earlier pre-review run deliberately terminated after the review finding,rc-15; it is not a pass |

The existing warning is Starlette's deprecation of its httpx TestClient
integration. Provider boundaries use synthetic replacements; scope, gateway,
PostgreSQL locks, RLS, history and audits remain real.

Affected regression commands:

```sh
.venv/bin/python -m pytest -q tests/test_evidence_contract.py \
  tests/service/test_evidence_transports.py -p no:cacheprovider --tb=short
.venv/bin/python -m pytest -q -s tests/service/test_evidence_upgrade.py \
  -p no:cacheprovider --tb=short
```

Both commands require the same isolated-cluster environment above. The full
suite uses `.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider` and
Playwright's installed Chromium with its system libraries. Do not run fixture
suites concurrently against the same shared test database.

## Upgrade and recovery

The [playbook](../playbooks/system/rag-063-source-evidence-upgrade.md) and its
[review/rehearsal record](../playbooks/system/rag-063-source-evidence-upgrade-review.md)
define the maintenance window, stopped-writer list, verified backup,029-only
migration, retry and recovery. Migration029 creates side tables, triggers and a
no-data lock helper; original rows, grants and historical audits remain intact.
Legacy records start at revision1 with no fabricated pre-upgrade decision history.
Subsequent writes advance revisions, including old0.6.15 clients' writes.

The corrected recovery fixture executes the playbook's dump-digest and public
inventory comparison snippets, rejects altered table/grant/owner/sequence
manifests, and changes only the copied configuration's database name. Archived
0.6.15 CLI status and an authenticated scoped0.6.15 REST read succeed against the
restored028 database; the0.6.16 service gate rejects it. Restoring the pre-upgrade
dump loses post-backup decisions and history, which the test confirms. The
upgraded database is retained for forward recovery. Remote-host restoration,
systemd/TLS restart and worker/timer resumption are deployment-specific checks.

## Review and remaining limits

The independent complete review inspected all51changed files at `96edf09`,
verified their hashes and executed collaborating-component success/recovery and
old-writer probes. It reported Medium RV063-M1 (manual attestations counted as
independent user events) and Important PB063-R1 (incomplete recovery procedure).
Both are independently confirmed fixed at `2c92d4d`. The re-review verified
52/52hashes, reused the41unchanged files from the first review, and inspected
all11changed/new files. No open Critical/High/Medium/Important finding remains.
The reviewer independently executed26edge checks and supplementary negative
probes of the playbook snippets.

The Low findings are retained in
[Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6537927613):
RV063-L1 derived-reader test naming/coverage; L2 terminal controls in plain-text
rendering; L3 retained history after deletion; L4 rare lock-helper error mapping.
Playbook minor findings PB063-R2/R3/R4 are independently confirmed fixed.
Additional minor findings PB063-N1/N2/N3 remain in
[Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6538060126):
system Python version, permission scope and the empty-target precondition.
PB063-N4 stale review-record wording is corrected. The restore manifest checks
table/sequence grants and owners; database CONNECT privileges, database/role
settings and function privileges need separate inspection for hardened stores.
The full history remains append-only, and legacy `get` provenance metadata
retains its previous shape. New opaque navigation does not promise global path
redaction from arbitrary memory content.

Merge approval and deployment are separate. No production database, provider
corpus, operating-system service or canonical worker was changed for Issue63.
