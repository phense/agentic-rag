---
id: V-060
title: Request tracing verification
type: reference
doc_id: issue60-tracing-verification
readers: [maintainer]
status: reviewed
version: 0.6.13
depends_on: [C-060]
assets: []
last_reviewed: 2026-10-30
summary: Source, isolated acceptance, independent review and measurements for Issue60; final full-suite proof and delivery boundaries.
---

# Request tracing verification

Issue60 adds metadata-only operational diagnosis across the service, queue and
dashboard. Source baseline is merged `75dc321` (0.6.12/schema025). The implementation
is isolated on `feat/request-tracing-60`; production installation and private
provider/corpus tests are outside this delivery. The final full suite and independent complete-diff review passed; merge approval
and deployment remain separate.

## Baseline evidence

| Check | Actual result | Boundary |
|---|---|---|
| Existing API/dashboard tests |8 passed,1 upstream Starlette/httpx warning,10.02s, exit0 | Owned PostgreSQL17 on55460, synthetic content |
| Release metadata check |0.6.12→0.6.13 consistent across pyproject, lock, badge and changelog; offline lock check exit0 | Recheck target at PR delivery/merge |

The initial default-port test attempt failed before tests could start because
PostgreSQL5432 required credentials. It was rerun against the separately owned
cluster55460; no production database or credential configuration was changed.

The unchanged baseline commit05af787 has the same complete tree as merged75dc321:
`907a867eaca9c0757ca7058266921f86e10665ec`. Matched measurements below use
the same owned tmpfs-backed PostgreSQL17 cluster55461 and scratch filesystem.
Earlier disk-backed measurements are diagnostic history, not this comparison.

Run the [measurement script](../benchmarks/2026-10-30-request-tracing/measure.py)
from each checked-out repository root, with that checkout's installed package:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE \
  PGPORT=55461 TMPDIR=/owned/tmpfs-scratch \
  .venv/bin/python /absolute/path/to/measure.py
```

Use an already running, separately owned PostgreSQL test cluster, not a production
port. The script creates and removes only its owned random `rag_bench_*` database,
loads synthetic policy and sends125 total `POST /v1/tools/memory_domains` calls
(5 warm-up,120 measured), using a four-thread caller. It drains responses and
records process descriptors, CPU, maximum RSS and optional metadata storage.
Both models point to a dead local port. Scratch paths are operator inputs.
The [machine-readable results](../benchmarks/2026-10-30-request-tracing/results.json)
retain the runtime/SQL/test source fingerprint and finite workload samples.

## Measured behavior and practical examples

| Matched HTTP sample | Before (0.6.12) | After (0.6.13, corrected source) |
|---|---:|---:|
| Successful measured calls / concurrency |120 /4 |120 /4 |
| Median / p95 |148.775 /240.479ms |183.896 /242.634ms |
| Caller CPU / elapsed |3.278 /4.775s |3.679 /5.609s |
| Process maximum RSS |93,648KiB |94,540KiB |
| Immediate descriptor count |8→8 |8→8 |
| Added metadata rows / serialized bytes / allocated relation |None |125 /81,944 /163,840B |

Five warm-ups are included in the125 stored rows. Both final samples ran after
the full suite, sequentially on the same owned cluster with no parallel owned
test workload. The observed median addition is35.121ms, p95 addition2.155ms,
caller CPU addition0.401s per120 calls, and maximum RSS addition892KiB. This is
one short in-process ASGI comparison on a shared development host, without an
inference workload. Earlier pairs under parallel test load varied in both
directions and remain in the raw results as diagnostic history. These numbers
are measured overhead for this sample, not a latency SLA or an inference-quality
gain. Descriptor counts are point samples; the separate40-connection test below
checks bounded retention. TLS, network, multi-day growth and target hardware are
outside this measurement. The capacity probe separately exercises nearly-full
metadata storage.

1. A source call now has a generated response UUID and a durable origin. The
   independently derived real HTTP/queue/worker probe observes202→queued→applied,
   exactly1 document and1 acceptance audit, and a foreign-department404. An enqueue
   is visibly different from completed extraction.
2. Under an exclusive trace-table lock, acceptance and its exact replay both
   return202 with the same receipt. There is exactly1 source window,1 queue entry
   and1 acceptance audit. The missing original trace stays404; the later replay
   trace links the original IDs and the retained job reaches applied.
3. At19,900 seeded rows,40 direct recorder attempts on4 threads yield39 captured
   and1 explicitly dropped/degraded in the targeted acceptance run, median114.444ms,
   p95197.637ms. The final19,939 rows account for23,920,131 conservative budget bytes
   versus10,767,055 actual serialized JSON bytes. Bounds are20,000 rows/64MiB;
   the finite150ms lock deadline remains enforced. This is a recorder probe,
   not an HTTP latency guarantee or a promise of complete capture under pressure.

The corrected-source full run also completed the existing real HTTP resource
test:40 simultaneous keep-alive connections,4,000 mixed light REST/MCP calls,
58.265s,800 HTTP200 and3,200 deliberate429 responses; all40 connections receive
successful service. This is admission/backpressure evidence, not4,000 successful
inferences or40 distinct identities. PSS rises50,107→51,527KiB with40 idle
connections, peaks53,453KiB, and changes52,597→53,405KiB between the sampled
warm/last points. Descriptors return10→8 after closure and are8 after100 successful
connection-turnover calls; only the single measuring database backend remains.
Database allocation rises10,204,851→11,024,051B (+819,200B), within the unchanged
1MiB assertion. Streams/windows/jobs stay0/0/4. These finite assertions passed in
the successful final full run; they do not prove a multi-day plateau.

## Acceptance gates

| Requirement | Required evidence | Current state |
|---|---|---|
| AC-001 metadata/identity | Generated IDs, fixed operation/status/bytes/time/version, no caller-supplied identity | Targeted and independent selection passed |
| AC-002 durable job origin | Source+foreground acceptance, replay, retry, prune and live outcome | Selection and independent real worker probes passed |
| AC-003 shared projections | REST/CLI/dashboard filters, keyset pagination, detail, export | Real Chromium and CLI passed; cursor/CLI corrections verified |
| AC-004 secret exclusion | Deliberate payload/query/header/exception fixtures, including MCP errors | Targeted and independent selection passed |
| AC-005 access | Current scope, realm separation, unknown/foreign IDs, empty scopes and revocation | Real SQL/HTTP/Chromium selection passed |
| AC-006 finite operation | Retention/capacity/locks/outage/concurrency, real storage reserve, degraded status | Targeted and independent selection passed |
| AC-007 existing install | Populated025 restore/upgrade/retry/originals, affected/full suites, review |31 original tables/60 original rows preserved;3 strict restores;026 once/retry no-op; final full suite exit0 |

Implementer selection:71 passed,1 upstream Starlette/httpx warning,37.78s, exit0.
Coordinator acceptance:22 passed,1 warning,36.68s, exit0. The cursor regression
first failed with AttributeError, then passed in3.51s; the real CLI detail
regression first failed with process exit4/UnboundLocalError, then its complete
Chromium/CLI flow passed in14.26s. Earlier green selections do not replace the
final corrected-source full suite.

## Independent review and playbook

Independent review inspected all37 initially changed files, base75dc321 to tree
18ff697, including actual callers and migration contracts. Follow-up review checked
both correction diffs and the identical published measurement script. The reviewer
ran34 tests (45.38s, exit0), independent source success/recovery probes (exit0),
and the corrected real CLI/browser flow (12.57s, exit0) on separate cluster55462.
No open Critical/High/Medium/feature Low findings remain:

- R060-01 (Low): numeric/null/object/list/bool cursor UUID could raise500.
  Typed safe UUID validation now returns400; adversarial regressions pass.
  Retained as [LOW-016 in #75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6522245599).
- R060-02 (Medium): a pre-existing branch-local UUID import shadowed the module
  import in the new CLI detail branch. Removing that redundant import restores
  `traces --detail`; a real subprocess regression compares its row with listing.

The reviewer derived the success/recovery paths from the sequence before
mapping them to tests. The operator guide is
[Find a request and follow its job](../16-request-tracing.md). Its scope is one
standalone medium task document. Independent PB-060 content review is Ready;
synthetic lookup/export/scope denial, source progression, outage/replay and
025→026 restore/retry rehearsals passed on2026-10-30. The real Chromium screenshot
was visually inspected. The glossary and prose/term checks passed;126 relative links resolve after
backlog/evidence reconciliation, and the final operator guide renders through
Pandoc. A separate operator probe ran the actual0.6.12 binary on the
owned026 database: it read a document created by0.6.13, saved a second document
and served capabilities. The isolated0.6.13 wheel's literal `trace-prune` command
then removed exactly1 expired trace while retaining both documents and all3 audit
rows. Production operations and long soak are not certified by these rehearsals.

All confirmed Critical/High/Medium bugs block PR delivery. New Low bugs go in
[#75](https://github.com/phense/agentic-rag/issues/75), explicitly confirmed by the
maintainer in this session. Existing LOW-012 describes a completed foreground
result retaining a previous deferral code; tracing must distinguish completed
success from that historical code without weakening result/audit atomicity.

[LOW-017](https://github.com/phense/agentic-rag/issues/75#issuecomment-6522728264)
tracks the open full-suite profile-refresh deadline investigation. The independent
follow-up verifies that test, fixtures and called profile/thematic/store/scope/SQL
paths are unchanged from the base and do not invoke tracing or query026 objects.
Its isolated rerun passes1 test in1.12s, exit0. There is no demonstrated tracing
regression and no established cause; Low describes observed suite stability,
not the severity of an unproven production failure. It remains open even if the
fresh full run passes. Another full failure requires order/plan/wait diagnosis.

## Delivery boundary

The initial full run was deliberately interrupted to correct R060-02; its partial
output is not a passing result. The first completed corrected-source full run exited1:1,589 passed,1 skipped,
1 upstream warning,1 failed in1,339.04s. The sole failure was an existing writer
profile-refresh preservation test: `thematic._state` exceeded its unchanged
statement timeout. The exact test passed alone on unchanged code in2.26s. Both
runtime/test source digests were identical before/after the full run. The fresh full run on the same source completed successfully: **1,590 passed,
1 skipped,1 upstream warning,1,408.03s, exit0**. The skip is the macOS-only
launchd installation check on Linux. No time/resource budget was increased.
The runner measured1,409.51s including startup/teardown and proved identical
SHA256 over all292 runtime/SQL/test files before and after:
`b07b684d891929c39bb6bf77347012da1ebc40d04f1bdd29b20fe6f298c78007`.
The failed prior run remains failed; LOW-017 stays open for its unknown cause.
OpenCode7 tests, JavaScript parse and offline lock consistency passed.
The0.6.13 wheel built successfully (SHA256
`8af7df9b5bb26964a277ea2295a1b320892749abaec8486fb467c2c30a369eb1`).
It was installed in a separate environment, aligned with the lockfile, and its
imports, packaged026 SQL, dashboard assets, CLI help and literal prune passed.

Code is ready for the per-PR handoff. No production deployment, migration, restart or credential
change is authorized by this implementation. Runtime measurements cover one
local synthetic workload. Per-PR approval follows the maintainer's requested
handoff; their subsequent “weiter” approves that specific PR's merge.
