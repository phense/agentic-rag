# Feature8: entity identity measurements

## Source, candidate and method

Source `2a29c50a2fa435d2caeb3354da9dbce92e85e6bb` is the adopted017 installation.
Measured candidate `c757fbfcfea5e9cc7655bb50a553c2dd3d4a2181` adds018 and explicit
entity reads. All application and measurement-driver bytes match the final PR;
[results.json](results.json) records their SHA256 fingerprints. Later activation
rehearsal commit `ac2532f` fixes only its final grant-inventory comparison; its
separate [activation-results.json](activation-results.json) records the tested
revision and literal playbook hash. Documentation changes do not affect these reads.

Both routes use the same name, exact project/domain, `as_of=2026-04-01T00:00:00Z`
and4800-character budget per query. Source uses ordinary lexical search, k8,
reranking off. Candidate uses the explicit structured entity API, at most100 facts;
these controlled oracles contain only one or two eligible facts, without crowding.
The baseline and candidate receive copies of the same original017 facts and alias
attestation notes. Only the candidate persists operator-confirmed relations.

Each case has one first observation and20 warm observations per route. Paired
route order alternates. First calls do not flush DB/OS caches and are not cold-cache
claims. API wall time excludes connection opening and citation/oracle validation;
source context formatting occurs after its API timer, candidate formatting inside
its API. Case3 sums the two independent project queries. Raw samples and all quality
observations are retained. These are API and retrieval measurements, not generated
answers or general production relevance scores.

## Three practical examples

| Case | Original evidence and question | Correct facts before→after, each warm observation | Stale current / foreign facts before→after | Context characters before→after |
| --- | --- | --- | --- | --- |
| Two names for one service | `orion` port8766, `orion-old` TLS enabled; ask `orion-old` after explicit confirmation |1/2→2/2 |0/0→0/0 |274→285 |
| Historical rename, current status | `cedar-old` stopped in January; explicit `cedar-new` replacement running in March; ask old name/status as of April |0/1→1/1 |1/0→0/0 |115→154 |
| Independent projects, identical names | `gateway-alt` links to each project's own `gateway`, north-running in alpha and south-offline in beta; ask each separately |0/2→2/2 |0/0→0/0 |0+0→162+162 |

Denominators are literal original assertion IDs labeled before indexing and alias
creation, independent of resolver eligibility. Every returned document is checked
against the requested project/domain and every assertion against the full oracle.
Original chunk spans and citations are checked. Across20 warm observations,
correct-fact totals are20/40→40/40,0/20→20/20 and0/40→40/40. The candidate has zero
stale, foreign, unexpected assertion or citation errors. The baseline old-status
fact remains a preserved historical fact; its exact-key API does not follow the
new-name replacement. Source result counts can include valid original alias notes,
which are not counted as recovered assertion facts.

| Case | First API ms before→after | Warm p50 ms before→after | Warm p95 ms before→after |
| --- | --- | --- | --- |
| Two names |17.733→15.905 |16.844→16.171 |17.513→18.000 |
| Historical rename |14.247→14.348 |15.759→15.659 |26.491→24.802 |
| Independent projects, two queries |27.654→41.035 |31.049→33.331 |40.291→39.345 |

No general speedup is claimed. The new API trades additional explicit identity
and validity selection for recovery of grounded facts. Context sizes rise here
because previously missing originals become available.

## Populated upgrade, interruption and recovery

The same driver creates017 through actual source CLI writes, with two actor
attributions, three domains, a pin, checkpoint, queue work, profile and original
alias claims. Candidate legacy CLI/MCP reads and writes work before018; optional
entity reads fail closed without aborting the caller transaction.

Strict source017 and target018 backups restore into separate owned empty databases
with a consistent exported snapshot, `--single-transaction --exit-on-error`; every
public table fingerprint and application-role grant matches. Applying018 preserves
original rows/grants. DDL rollback and migration retry pass. A rolled-back two-row
backfill has zero attachments; four resumed batches map7 known facts, report one
unresolved unknown, and a no-op adds no audit. Source/new/source CLI citations match;
fresh MCP tools are9/15→10/18→9/15. Three actual overlapping source assertion/new
alias process pairs sharing original evidence complete and recover the fact.

A checksum-verified private017 snapshot was restored only into an owned database:
18 public tables,10571 documents,11961 chunks,607 assertions,22 pins,7 domains,
26 checkpoints,1406 queue rows,1016 batches and all37689 historical audits are
preserved. Seven audited backfill batches map607 assertions; no aliases are
inferred, remaining0 and no-change retry adds no audit. Public output contains
counts only; original identifiers, bodies, credentials and dump paths stay private.

The separate activation driver executes the exact PB-5.8 migration/backfill/Git
fast-forward and code-recovery snippets. It rejects unsupported/abbreviated
revisions, dirty/wrong candidates, wrong imported modules/SQL paths, checkout drift
before and after locking, and a busy private worker lock. Completed018 activation
retry and detached source-code recovery retain originals, grants,018 and the prior
branch tip. Original CLI citations match; lock reacquisition and owned cleanup pass.
The candidate's temporary owned dirty-marker test is disclosed in its raw report.

## Trading read-only controls and limits

Live017 Trading contains4357 documents at observation. Three ordinary lexical
queries,20 warm repetitions each, return eight valid original citations each:

| Query | First ms | Warm p50 ms | Warm p95 ms |
| --- | --- | --- | --- |
| portfolio |180.087 |71.521 |79.160 |
| earnings |141.403 |81.358 |85.934 |
| regime |221.862 |163.845 |173.288 |

These controls use a reader-only transaction, zero application writes and zero
provider calls. They do not measure production alias quality: no live aliases or
018 tables were created. No production migration, deployment or service interruption
occurred. Shared reader roles are not per-user ACLs; exact project/domain selection
was tested. Historical trust is evaluated currently, arbitrary source-version
upgrades are unsupported, and existing exact-key cross-domain deduplication cannot
recover facts already omitted by older writers. Same-name generations in one
boundary require operator qualification. Large-corpus identity-read latency remains
unmeasured; SQL/result limits bound waits/output, not constant scan cost.

## Reproduce on authorized owned fixtures

Use the canonical interpreter from the candidate root with its `PYTHONPATH`:

```bash
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_entity_identities.py --repeats 20 --trading \
  --private-recovery-dump /private/operator-selected/source017.dump \
  --private-recovery-report /private/operator-selected/source017-report.json \
  --output /private/operator-selected/entity-results.json
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_entity_activation.py /private/operator-selected/activation-results.json
```

The private-recovery options require a locally checksum-verified source017 backup;
omit both for controlled public fixtures only. `--trading` is read-only. No command
above authorizes production adoption. See [verification](../../verification/entity-identities.md),
[reference](../../entity-identities.md) and [PB-5.8](../../playbooks/entity-identities.md).
